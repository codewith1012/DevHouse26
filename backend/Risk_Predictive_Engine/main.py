import json
import os
from typing import Any, Optional
from urllib import error, parse, request

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from engine import build_requirement_risk

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL") or os.getenv("VITE_SUPABASE_URL")
SUPABASE_API_KEY = (
    os.getenv("SUPABASE_SERVICE_KEY")
    or os.getenv("SUPABASE_ANON_KEY")
    or os.getenv("VITE_SUPABASE_ANON_KEY")
)
BASE_REST_URL = f"{(SUPABASE_URL or '').rstrip('/')}/rest/v1"

DEFAULT_HEADERS = {
    "apikey": SUPABASE_API_KEY,
    "Authorization": f"Bearer {SUPABASE_API_KEY}",
}
ENGINE_VERSION = "v1"

app = FastAPI(title="Requirement Risk Predictive Engine")


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


def get_issue(issue_id: str) -> dict[str, Any]:
    rows = request_json(
        "GET",
        f"{BASE_REST_URL}/req_code_mapping?select=issue_id,title,status,priority,assignee_email,jira_created_at,due_date,commits&issue_id=eq.{parse.quote(issue_id)}&limit=1",
    )
    if not isinstance(rows, list) or not rows:
        raise HTTPException(status_code=404, detail=f"Requirement {issue_id} not found")
    return rows[0]


def get_issue_events(issue_id: str) -> list[dict[str, Any]]:
    rows = request_json(
        "GET",
        f"{BASE_REST_URL}/extension_events?select=commit_id,timestamp,total_changes,author,author_email,repository_name,issue_id&issue_id=eq.{parse.quote(issue_id)}&limit=500&order=timestamp.desc",
    )
    if not isinstance(rows, list):
        raise HTTPException(status_code=500, detail="Unexpected extension_events response")
    return rows


def serialize_risk_record(issue: dict[str, Any], risk: dict[str, Any]) -> dict[str, Any]:
    return {
        "requirement_id": risk.get("requirement_id"),
        "title": risk.get("title") or issue.get("title"),
        "status": issue.get("status"),
        "due_date": issue.get("due_date"),
        "days_remaining": risk.get("time", {}).get("days_remaining"),
        "risk_score": risk.get("risk_score"),
        "risk_level": risk.get("risk_level"),
        "breakdown": risk.get("breakdown") or {},
        "reasons": risk.get("reasons") or [],
        "recommendations": risk.get("recommendations") or [],
        "inputs": risk.get("inputs") or {},
        "engine_version": ENGINE_VERSION,
        "calculated_at": risk.get("time", {}).get("current_date"),
    }


def persist_requirement_risk(issue: dict[str, Any], risk: dict[str, Any]) -> dict[str, Any]:
    record = serialize_risk_record(issue, risk)
    upsert_row("requirement_risk_scores", record, on_conflict="requirement_id")
    return record


def calculate_and_store_requirement_risk(issue_id: str) -> dict[str, Any]:
    issue = get_issue(issue_id)
    events = get_issue_events(issue_id)
    risk = build_requirement_risk(issue, events)
    persist_requirement_risk(issue, risk)
    return risk


def get_stored_risk(issue_id: str) -> Optional[dict[str, Any]]:
    rows = request_json(
        "GET",
        f"{BASE_REST_URL}/requirement_risk_scores?select=requirement_id,title,status,due_date,days_remaining,risk_score,risk_level,breakdown,reasons,recommendations,inputs,engine_version,calculated_at&requirement_id=eq.{parse.quote(issue_id)}&limit=1",
    )
    if isinstance(rows, list) and rows:
        return rows[0]
    return None


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "service": "requirement-risk-engine"}


@app.get("/api/risk/requirement/{issue_id}")
def get_requirement_risk(issue_id: str, refresh: bool = False) -> dict[str, Any]:
    if refresh:
        return calculate_and_store_requirement_risk(issue_id)

    stored = get_stored_risk(issue_id)
    if stored:
        return stored
    return calculate_and_store_requirement_risk(issue_id)


@app.get("/api/risk/requirements")
def list_requirement_risks(limit: int = 12, refresh: bool = False) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit), 50))
    if refresh:
        return recalculate_requirement_risks(limit=safe_limit)

    rows = request_json(
        "GET",
        f"{BASE_REST_URL}/requirement_risk_scores?select=requirement_id,title,status,due_date,days_remaining,risk_score,risk_level,breakdown,reasons,recommendations,inputs,engine_version,calculated_at&limit={safe_limit}&order=risk_score.desc",
    )
    if not isinstance(rows, list):
        raise HTTPException(status_code=500, detail="Unexpected requirement_risk_scores response")
    if rows:
        return {"requirements": rows}
    return recalculate_requirement_risks(limit=safe_limit)


@app.post("/api/risk/recalculate")
def recalculate_requirement_risks(limit: int = 25) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit), 100))
    issues = request_json(
        "GET",
        f"{BASE_REST_URL}/req_code_mapping?select=issue_id,title,status,priority,assignee_email,jira_created_at,due_date,commits&limit={safe_limit}&order=updated_at.desc",
    )
    if not isinstance(issues, list):
        raise HTTPException(status_code=500, detail="Unexpected req_code_mapping response")

    requirements = []
    for issue in issues:
        issue_id = str(issue.get("issue_id") or "").strip()
        if not issue_id:
            continue
        events = get_issue_events(issue_id)
        risk = build_requirement_risk(issue, events)
        persist_requirement_risk(issue, risk)
        requirements.append(risk)

    requirements.sort(key=lambda item: item["risk_score"], reverse=True)
    return {"requirements": requirements}


@app.post("/api/risk/recalculate/{issue_id}")
def recalculate_single_requirement(issue_id: str) -> dict[str, Any]:
    return calculate_and_store_requirement_risk(issue_id)
