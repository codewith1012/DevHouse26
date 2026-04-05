import json
import os
from pathlib import Path
from typing import Any, Optional
from urllib import error, parse, request

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from engine import build_heuristic_estimate, build_llm_prompt, combine_estimates, parse_datetime, summarize_commit_metrics

ROOT_DIR = Path(__file__).resolve().parent
load_dotenv(ROOT_DIR / ".env")
load_dotenv(ROOT_DIR.parent / "Req_codeMapping" / ".env", override=False)
load_dotenv(ROOT_DIR.parent / "Risk_Predictive_Engine" / ".env", override=False)

SUPABASE_URL = os.getenv("SUPABASE_URL") or os.getenv("VITE_SUPABASE_URL")
SUPABASE_API_KEY = (
    os.getenv("SUPABASE_SERVICE_KEY")
    or os.getenv("SUPABASE_ANON_KEY")
    or os.getenv("VITE_SUPABASE_ANON_KEY")
)
BASE_REST_URL = f"{(SUPABASE_URL or '').rstrip('/')}/rest/v1"
OLLAMA_URL = (os.getenv("OLLAMA_URL") or "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:latest")
ENGINE_VERSION = os.getenv("EFFORT_ENGINE_VERSION", "v1")

DEFAULT_HEADERS = {
    "apikey": SUPABASE_API_KEY,
    "Authorization": f"Bearer {SUPABASE_API_KEY}",
}

app = FastAPI(title="Requirement Effort Estimation Engine")


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


def upsert_row(table: str, payload: dict[str, Any], on_conflict: str) -> Any:
    headers = {
        **DEFAULT_HEADERS,
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=representation",
    }
    conflict = parse.urlencode({"on_conflict": on_conflict})
    return request_json("POST", f"{BASE_REST_URL}/{table}?{conflict}", payload=[payload], headers=headers)


def get_requirement(issue_id: str) -> dict[str, Any]:
    rows = request_json(
        "GET",
        f"{BASE_REST_URL}/req_code_mapping?select=issue_id,title,description,status,issue_type,priority,assignee_email,jira_created_at,due_date,commits&issue_id=eq.{parse.quote(issue_id)}&limit=1",
    )
    if not isinstance(rows, list) or not rows:
        raise HTTPException(status_code=404, detail=f"Requirement {issue_id} not found")
    return rows[0]


def get_requirement_events(issue_id: str) -> list[dict[str, Any]]:
    rows = request_json(
        "GET",
        f"{BASE_REST_URL}/extension_events?select=commit_id,timestamp,total_changes,additions,deletions,author,author_email,repository_name,branch,issue_id&issue_id=eq.{parse.quote(issue_id)}&limit=500&order=timestamp.asc",
    )
    if not isinstance(rows, list):
        raise HTTPException(status_code=500, detail="Unexpected extension_events response")
    return rows


def get_stored_estimate(issue_id: str) -> Optional[dict[str, Any]]:
    rows = request_json(
        "GET",
        f"{BASE_REST_URL}/requirement_effort_estimates?select=requirement_id,title,status,due_date,initial_estimate_hours,heuristic_estimate_hours,llm_estimate_hours,final_estimate_hours,remaining_estimate_hours,completed_effort_hours,confidence,estimate_level,drift_hours,drift_direction,breakdown,rationale,task_breakdown,inputs,engine_version,calculated_at&requirement_id=eq.{parse.quote(issue_id)}&limit=1",
    )
    if isinstance(rows, list) and rows:
        return rows[0]
    return None


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


def _coerce_relaxed_json(text: str) -> str:
    normalized = text.strip()
    if not normalized:
        return ""
    normalized = normalized.replace("\r\n", "\n")
    return normalized


def extract_json_block(text: str) -> Optional[dict[str, Any]]:
    candidates = [text]
    fenced = _extract_fenced_code(text)
    if fenced:
        candidates.insert(0, fenced)

    for candidate in candidates:
        cleaned = _coerce_relaxed_json(candidate)
        if not cleaned:
            continue
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue
    return None


def query_ollama_effort(issue: dict[str, Any], commit_metrics: dict[str, Any], heuristic: dict[str, Any]) -> Optional[dict[str, Any]]:
    body = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are DevHouse Effort AI. "
                    "Estimate software requirement effort using the supplied requirement and commit execution signals. "
                    "Return JSON only."
                ),
            },
            {
                "role": "user",
                "content": build_llm_prompt(issue, commit_metrics, heuristic),
            },
        ],
    }

    try:
        response = requests.post(f"{OLLAMA_URL}/api/chat", json=body, timeout=180)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        print(f"[EFFORT] Ollama estimate unavailable for {issue.get('issue_id')}: {exc}")
        return None

    message = payload.get("message") or {}
    content = str(message.get("content") or "").strip()
    parsed = extract_json_block(content)
    if not parsed:
        print(f"[EFFORT] Ollama returned non-JSON estimate for {issue.get('issue_id')}")
        return None
    return parsed


def serialize_estimate_record(issue: dict[str, Any], estimate: dict[str, Any]) -> dict[str, Any]:
    return {
        "requirement_id": issue.get("issue_id"),
        "title": issue.get("title"),
        "status": issue.get("status"),
        "due_date": issue.get("due_date"),
        "initial_estimate_hours": estimate.get("initial_estimate_hours"),
        "heuristic_estimate_hours": estimate.get("heuristic_estimate_hours"),
        "llm_estimate_hours": estimate.get("llm_estimate_hours"),
        "final_estimate_hours": estimate.get("final_estimate_hours"),
        "remaining_estimate_hours": estimate.get("remaining_estimate_hours"),
        "completed_effort_hours": estimate.get("completed_effort_hours"),
        "confidence": estimate.get("confidence"),
        "estimate_level": estimate.get("estimate_level"),
        "drift_hours": estimate.get("drift_hours"),
        "drift_direction": estimate.get("drift_direction"),
        "breakdown": estimate.get("breakdown") or {},
        "rationale": estimate.get("rationale") or [],
        "task_breakdown": estimate.get("task_breakdown") or [],
        "inputs": estimate.get("inputs") or {},
        "engine_version": ENGINE_VERSION,
        "calculated_at": estimate.get("calculated_at"),
    }


def calculate_requirement_estimate(issue_id: str) -> dict[str, Any]:
    issue = get_requirement(issue_id)
    events = get_requirement_events(issue_id)
    from datetime import datetime, timezone

    current_time = datetime.now(timezone.utc)

    previous = get_stored_estimate(issue_id)
    previous_hours = float(previous.get("final_estimate_hours")) if previous and previous.get("final_estimate_hours") is not None else None

    commit_metrics = summarize_commit_metrics(events, current_time)
    heuristic = build_heuristic_estimate(issue, commit_metrics, current_time)
    llm_estimate = query_ollama_effort(issue, commit_metrics, heuristic)
    combined = combine_estimates(heuristic, llm_estimate, previous_hours)

    estimate = {
        "requirement_id": issue.get("issue_id"),
        "title": issue.get("title"),
        "status": issue.get("status"),
        "due_date": issue.get("due_date"),
        "initial_estimate_hours": heuristic.get("initial_estimate_hours"),
        **combined,
        "breakdown": {
            **(heuristic.get("breakdown") or {}),
            "commit_metrics": commit_metrics,
        },
        "inputs": {
            "issue_type": issue.get("issue_type"),
            "priority": issue.get("priority"),
            "jira_created_at": issue.get("jira_created_at"),
            "due_date": issue.get("due_date"),
            "commit_metrics": commit_metrics,
        },
        "calculated_at": current_time.isoformat(),
    }

    record = serialize_estimate_record(issue, estimate)
    upsert_row("requirement_effort_estimates", record, on_conflict="requirement_id")
    return record


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "requirement-effort-estimation-engine",
        "ollama_url": OLLAMA_URL,
        "model": OLLAMA_MODEL,
    }


@app.get("/api/effort/requirement/{issue_id}")
def get_requirement_effort(issue_id: str, refresh: bool = False) -> dict[str, Any]:
    if refresh:
        return calculate_requirement_estimate(issue_id)

    stored = get_stored_estimate(issue_id)
    if stored:
        return stored
    return calculate_requirement_estimate(issue_id)


@app.get("/api/effort/requirements")
def list_requirement_efforts(limit: int = 12, refresh: bool = False) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit), 50))
    if refresh:
        return recalculate_requirement_efforts(limit=safe_limit)

    rows = request_json(
        "GET",
        f"{BASE_REST_URL}/requirement_effort_estimates?select=requirement_id,title,status,due_date,initial_estimate_hours,heuristic_estimate_hours,llm_estimate_hours,final_estimate_hours,remaining_estimate_hours,completed_effort_hours,confidence,estimate_level,drift_hours,drift_direction,breakdown,rationale,task_breakdown,inputs,engine_version,calculated_at&limit={safe_limit}&order=final_estimate_hours.desc",
    )
    if not isinstance(rows, list):
        raise HTTPException(status_code=500, detail="Unexpected requirement_effort_estimates response")
    if rows:
        return {"requirements": rows}
    return recalculate_requirement_efforts(limit=safe_limit)


@app.post("/api/effort/recalculate")
def recalculate_requirement_efforts(limit: int = 25) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit), 100))
    issues = request_json(
        "GET",
        f"{BASE_REST_URL}/req_code_mapping?select=issue_id,title,status,priority,issue_type,assignee_email,jira_created_at,due_date,commits&limit={safe_limit}&order=updated_at.desc",
    )
    if not isinstance(issues, list):
        raise HTTPException(status_code=500, detail="Unexpected req_code_mapping response")

    requirements = []
    for issue in issues:
        issue_id = str(issue.get("issue_id") or "").strip()
        if not issue_id:
            continue
        requirements.append(calculate_requirement_estimate(issue_id))

    requirements.sort(key=lambda item: float(item.get("final_estimate_hours") or 0), reverse=True)
    return {"requirements": requirements}


@app.post("/api/effort/recalculate/{issue_id}")
def recalculate_single_requirement(issue_id: str) -> dict[str, Any]:
    return calculate_requirement_estimate(issue_id)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8003")), reload=True)
