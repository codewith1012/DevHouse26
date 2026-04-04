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


def request_json(method: str, url: str, payload: Optional[Any] = None) -> Any:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = request.Request(url, method=method, headers=DEFAULT_HEADERS, data=data)
    try:
        with request.urlopen(req, timeout=60) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else None
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise HTTPException(status_code=exc.code, detail=detail) from exc
    except error.URLError as exc:
        raise HTTPException(status_code=502, detail=str(exc.reason)) from exc


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


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "service": "requirement-risk-engine"}


@app.get("/api/risk/requirement/{issue_id}")
def get_requirement_risk(issue_id: str) -> dict[str, Any]:
    issue = get_issue(issue_id)
    events = get_issue_events(issue_id)
    return build_requirement_risk(issue, events)


@app.get("/api/risk/requirements")
def list_requirement_risks(limit: int = 12) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit), 50))
    issues = request_json(
        "GET",
        f"{BASE_REST_URL}/req_code_mapping?select=issue_id,title,status,priority,assignee_email,jira_created_at,due_date,commits&limit={safe_limit}&order=updated_at.desc",
    )
    if not isinstance(issues, list):
        raise HTTPException(status_code=500, detail="Unexpected req_code_mapping response")

    rows = []
    for issue in issues:
        issue_id = str(issue.get("issue_id") or "").strip()
        if not issue_id:
            continue
        events = get_issue_events(issue_id)
        rows.append(build_requirement_risk(issue, events))

    rows.sort(key=lambda item: item["risk_score"], reverse=True)
    return {"requirements": rows}
