import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional
from urllib import error, parse, request

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL") or os.getenv("VITE_SUPABASE_URL")
SUPABASE_API_KEY = (
    os.getenv("SUPABASE_SERVICE_KEY")
    or os.getenv("SUPABASE_ANON_KEY")
    or os.getenv("VITE_SUPABASE_ANON_KEY")
)
BASE_REST_URL = f"{(SUPABASE_URL or '').rstrip('/')}/rest/v1"
OLLAMA_URL = (os.getenv("OLLAMA_URL") or "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3:latest")
PORT = int(os.getenv("PORT", "8010"))

DEFAULT_HEADERS = {
    "apikey": SUPABASE_API_KEY,
    "Authorization": f"Bearer {SUPABASE_API_KEY}",
}

app = FastAPI(title="DevHouse AI Prompt Engine")


class Selection(BaseModel):
    start_line: int
    start_character: int
    end_line: int
    end_character: int


class AIQueryRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    mode: str = Field(default="ask")
    developer_id: str
    repository_name: str
    issue_id: Optional[str] = None
    model: Optional[str] = None
    file_path: Optional[str] = None
    language: Optional[str] = None
    selected_text: Optional[str] = ""
    surrounding_code: Optional[str] = ""
    selection: Optional[Selection] = None


def parse_allowed_origins() -> list[str]:
    configured = os.getenv("ALLOWED_ORIGINS", "")
    parsed = [origin.strip().rstrip("/") for origin in configured.split(",") if origin.strip()]
    defaults = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        (os.getenv("FRONTEND_URL") or "http://localhost:5173").rstrip("/"),
    ]

    seen: set[str] = set()
    origins: list[str] = []
    for origin in [*defaults, *parsed]:
        if origin and origin not in seen:
            seen.add(origin)
            origins.append(origin)
    return origins


app.add_middleware(
    CORSMiddleware,
    allow_origins=parse_allowed_origins(),
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def request_json(method: str, url: str, payload: Optional[Any] = None, headers: Optional[dict[str, str]] = None) -> Any:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = request.Request(url, method=method, headers=headers or DEFAULT_HEADERS, data=data)
    try:
        with request.urlopen(req, timeout=60) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else None
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise HTTPException(status_code=exc.code, detail=detail) from exc
    except error.URLError as exc:
        raise HTTPException(status_code=502, detail=str(exc.reason)) from exc


def insert_ai_event(payload: dict[str, Any]) -> dict[str, Any]:
    headers = {
        **DEFAULT_HEADERS,
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    response = request_json("POST", f"{BASE_REST_URL}/ai_events", payload=[payload], headers=headers)
    if isinstance(response, list) and response:
        return response[0]
    return payload


def build_system_prompt(mode: str, language: Optional[str]) -> str:
    language_hint = f"Target language is {language}." if language else "Preserve the current file language."
    if mode == "refactor":
        return (
            "You are DevHouse AI, an inline coding assistant. "
            f"{language_hint} "
            "Return JSON only with keys: answer, edit. "
            "The edit object must include kind='replace_selection' and content containing only the replacement code."
        )
    if mode == "generate":
        return (
            "You are DevHouse AI, an inline coding assistant. "
            f"{language_hint} "
            "Return JSON only with keys: answer, edit. "
            "The edit object must include kind='insert_at_cursor' and content containing only the code to insert."
        )
    return (
        "You are DevHouse AI, a concise code assistant. "
        "Return practical engineering help. If you provide code, include it in fenced code blocks."
    )


def build_user_prompt(req: AIQueryRequest) -> str:
    parts = [
        f"Mode: {req.mode}",
        f"Developer prompt: {req.prompt}",
    ]
    if req.issue_id:
        parts.append(f"Active Jira issue: {req.issue_id}")
    if req.file_path:
        parts.append(f"File path: {req.file_path}")
    if req.language:
        parts.append(f"Language: {req.language}")
    if req.selected_text:
        parts.append(f"Selected code:\n{req.selected_text}")
    if req.surrounding_code:
        parts.append(f"Visible code context:\n{req.surrounding_code[:12000]}")
    return "\n\n".join(parts)


def query_ollama(req: AIQueryRequest) -> tuple[str, int, int, str]:
    model = req.model or OLLAMA_MODEL
    body = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": build_system_prompt(req.mode, req.language)},
            {"role": "user", "content": build_user_prompt(req)},
        ],
    }

    try:
        response = requests.post(f"{OLLAMA_URL}/api/chat", json=body, timeout=180)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Ollama request failed: {exc}") from exc

    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=response.text)

    payload = response.json()
    message = payload.get("message") or {}
    content = str(message.get("content") or "").strip()
    input_tokens = int(payload.get("prompt_eval_count") or 0)
    output_tokens = int(payload.get("eval_count") or 0)
    return content, input_tokens, output_tokens, model


def extract_json_block(text: str) -> Optional[dict[str, Any]]:
    candidates = [text]
    fenced = _extract_fenced_code(text)
    if fenced:
        candidates.insert(0, fenced)

    for candidate in candidates:
        cleaned = candidate.strip()
        if not cleaned:
            continue
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            relaxed = _coerce_relaxed_json(cleaned)
            if not relaxed:
                continue
            try:
                parsed = json.loads(relaxed)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue
    return None


def _coerce_relaxed_json(text: str) -> str:
    """
    Handles common LLM almost-JSON patterns such as triple-quoted multiline strings.
    """
    normalized = text.strip()
    if not normalized:
        return ""

    pattern = re.compile(r'("content"\s*:\s*)"""([\s\S]*?)"""')

    def replace_content(match: re.Match[str]) -> str:
        prefix = match.group(1)
        raw_content = match.group(2)
        return f'{prefix}{json.dumps(raw_content)}'

    normalized = pattern.sub(replace_content, normalized)
    return normalized


def _extract_fenced_code(text: str) -> str:
    start = text.find("```")
    if start == -1:
        return ""
    remainder = text[start + 3 :]
    newline = remainder.find("\n")
    if newline == -1:
        return ""
    remainder = remainder[newline + 1 :]
    end = remainder.find("```")
    if end == -1:
        return ""
    return remainder[:end].strip()


def build_edit_response(mode: str, raw_output: str) -> tuple[str, Optional[dict[str, Any]]]:
    parsed = extract_json_block(raw_output)
    if parsed:
        answer = str(parsed.get("answer") or parsed.get("response") or "").strip()
        edit = parsed.get("edit")
        if isinstance(edit, dict):
            return answer, edit
        return answer, None

    extracted_code = _extract_fenced_code(raw_output)
    if mode == "generate" and extracted_code:
        return raw_output, {"kind": "insert_at_cursor", "content": extracted_code}
    if mode == "refactor" and extracted_code:
        return raw_output, {"kind": "replace_selection", "content": extracted_code}
    return raw_output, None


def score_prompt(prompt: str, response_text: str, input_tokens: int, output_tokens: int) -> float:
    prompt_length_score = min(len(prompt.strip()) / 120, 1.0)
    response_presence = 1.0 if response_text.strip() else 0.0
    token_efficiency = 1.0 if (input_tokens + output_tokens) <= 600 else max(0.2, 600 / max(input_tokens + output_tokens, 1))
    return round(min((prompt_length_score * 0.35) + (response_presence * 0.35) + (token_efficiency * 0.30), 1.0), 4)


def score_efficiency(prompt_score: float, input_tokens: int, output_tokens: int) -> float:
    total_tokens = max(input_tokens + output_tokens, 1)
    return round(min((prompt_score * 200) / total_tokens, 1.0), 4)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "devhouse-ai-prompt-engine",
        "ollama_url": OLLAMA_URL,
        "model": OLLAMA_MODEL,
    }


@app.post("/api/ai/query")
def ai_query(req: AIQueryRequest) -> dict[str, Any]:
    mode = req.mode.lower().strip()
    if mode not in {"ask", "generate", "refactor"}:
        raise HTTPException(status_code=400, detail="mode must be one of: ask, generate, refactor")

    prompt = req.prompt.strip()
    if len(prompt) < 3:
        raise HTTPException(status_code=400, detail="Prompt is too short")

    raw_output, input_tokens, output_tokens, model = query_ollama(req)
    answer, edit = build_edit_response(mode, raw_output)
    prompt_score = score_prompt(prompt, answer or raw_output, input_tokens, output_tokens)
    efficiency_score = score_efficiency(prompt_score, input_tokens, output_tokens)

    stored = insert_ai_event(
        {
            "prompt": prompt,
            "response": (answer or raw_output)[:8000] if (answer or raw_output) else None,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "model": model,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "developer_id": req.developer_id,
            "repository_name": req.repository_name,
            "issue_id": req.issue_id,
            "commit_id": None,
            "prompt_score": prompt_score,
            "efficiency_score": efficiency_score,
        }
    )

    usage = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }

    response_payload: dict[str, Any] = {
        "id": stored.get("id"),
        "response": answer or raw_output,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "usage": usage,
        "prompt_score": prompt_score,
        "efficiency_score": efficiency_score,
    }
    if edit:
        response_payload["edit"] = edit
    return response_payload


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=True)
