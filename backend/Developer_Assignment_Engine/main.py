import json
import os
from pathlib import Path
from typing import Any, Optional
from urllib import error, parse, request

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from engine import build_developer_recommendations

ROOT_DIR = Path(__file__).resolve().parent
load_dotenv(ROOT_DIR / ".env")
load_dotenv(ROOT_DIR.parent / "Req_codeMapping" / ".env", override=False)

SUPABASE_URL = os.getenv("SUPABASE_URL") or os.getenv("VITE_SUPABASE_URL")
SUPABASE_API_KEY = (
    os.getenv("SUPABASE_SERVICE_KEY")
    or os.getenv("SUPABASE_ANON_KEY")
    or os.getenv("VITE_SUPABASE_ANON_KEY")
)
BASE_REST_URL = f"{(SUPABASE_URL or '').rstrip('/')}/rest/v1"
ENGINE_VERSION = os.getenv("ASSIGNMENT_ENGINE_VERSION", "v1")

DEFAULT_HEADERS = {
    "apikey": SUPABASE_API_KEY,
    "Authorization": f"Bearer {SUPABASE_API_KEY}",
}

app = FastAPI(title="Developer Assignment Recommendation Engine")


class DeveloperPayload(BaseModel):
    developer_id: str = Field(..., min_length=2)
    name: str = Field(..., min_length=1)
    email: Optional[str] = None
    age: Optional[int] = None
    role: Optional[str] = None
    experience_years: float = 0.0
    seniority_level: str = "mid"
    tech_stack: list[str] = Field(default_factory=list)
    summary: Optional[str] = None
    current_capacity: int = 3
    active: bool = True


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


def get_rows(table: str, select: str, order: Optional[str] = None, limit: Optional[int] = None) -> list[dict[str, Any]]:
    params = {"select": select}
    if order:
        params["order"] = order
    if limit:
        params["limit"] = str(limit)
    query = parse.urlencode(params, safe="*,()")
    response = request_json("GET", f"{BASE_REST_URL}/{table}?{query}")
    if not isinstance(response, list):
        raise HTTPException(status_code=500, detail=f"Unexpected response for {table}")
    return response


def delete_rows(table: str, filters: str) -> Any:
    headers = {**DEFAULT_HEADERS, "Prefer": "return=representation"}
    return request_json("DELETE", f"{BASE_REST_URL}/{table}?{filters}", headers=headers)


def insert_rows(table: str, payload: list[dict[str, Any]]) -> Any:
    headers = {
        **DEFAULT_HEADERS,
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    return request_json("POST", f"{BASE_REST_URL}/{table}", payload=payload, headers=headers)


def upsert_rows(table: str, payload: list[dict[str, Any]], on_conflict: str) -> Any:
    headers = {
        **DEFAULT_HEADERS,
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=representation",
    }
    conflict = parse.urlencode({"on_conflict": on_conflict})
    return request_json("POST", f"{BASE_REST_URL}/{table}?{conflict}", payload=payload, headers=headers)


def get_requirement(issue_id: str) -> dict[str, Any]:
    rows = request_json(
        "GET",
        f"{BASE_REST_URL}/req_code_mapping?select=issue_id,title,description,status,issue_type,priority,due_date,commits&issue_id=eq.{parse.quote(issue_id)}&limit=1",
    )
    if not isinstance(rows, list) or not rows:
        raise HTTPException(status_code=404, detail=f"Requirement {issue_id} not found")
    return rows[0]


def get_requirement_events(issue_id: str) -> list[dict[str, Any]]:
    rows = request_json(
        "GET",
        f"{BASE_REST_URL}/extension_events?select=issue_id,developer_id,author,author_email,repository_name,branch,timestamp,total_changes&issue_id=eq.{parse.quote(issue_id)}&limit=300&order=timestamp.desc",
    )
    if not isinstance(rows, list):
        raise HTTPException(status_code=500, detail="Unexpected extension_events response")
    return rows


def get_all_events(limit: int = 2000) -> list[dict[str, Any]]:
    return get_rows(
        "extension_events",
        "issue_id,developer_id,author,author_email,repository_name,branch,timestamp,total_changes",
        order="timestamp.desc",
        limit=limit,
    )


def get_developers(limit: int = 200) -> list[dict[str, Any]]:
    return get_rows(
        "developers",
        "developer_id,name,email,age,role,experience_years,seniority_level,tech_stack,summary,current_capacity,active",
        order="name.asc",
        limit=limit,
    )


def get_stored_recommendations(issue_id: str) -> list[dict[str, Any]]:
    rows = request_json(
        "GET",
        f"{BASE_REST_URL}/requirement_developer_recommendations?select=requirement_id,developer_id,developer_name,developer_email,role,experience_years,tech_stack,score,rank,skill_match,familiarity_match,experience_fit,availability_score,reasons,breakdown,engine_version,calculated_at&requirement_id=eq.{parse.quote(issue_id)}&order=score.desc&limit=5",
    )
    return rows if isinstance(rows, list) else []


def persist_recommendations(issue_id: str, recommendations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    delete_rows("requirement_developer_recommendations", f"requirement_id=eq.{parse.quote(issue_id)}")
    if not recommendations:
        return []

    payload = []
    for item in recommendations[:5]:
        payload.append(
            {
                "requirement_id": item["requirement_id"],
                "developer_id": item["developer_id"],
                "developer_name": item.get("developer_name"),
                "developer_email": item.get("developer_email"),
                "role": item.get("role"),
                "experience_years": item.get("experience_years"),
                "tech_stack": item.get("tech_stack") or [],
                "score": item["score"],
                "rank": item["rank"],
                "skill_match": item["skill_match"],
                "familiarity_match": item["familiarity_match"],
                "experience_fit": item["experience_fit"],
                "availability_score": item["availability_score"],
                "reasons": item.get("reasons") or [],
                "breakdown": item.get("breakdown") or {},
                "engine_version": ENGINE_VERSION,
            }
        )

    insert_rows("requirement_developer_recommendations", payload)
    return payload


def calculate_and_store_recommendations(issue_id: str) -> dict[str, Any]:
    issue = get_requirement(issue_id)
    developers = get_developers()
    issue_events = get_requirement_events(issue_id)
    all_events = get_all_events()
    ranked = build_developer_recommendations(issue, developers, issue_events, all_events)
    stored = persist_recommendations(issue_id, ranked)
    return {
        "requirement_id": issue.get("issue_id"),
        "title": issue.get("title"),
        "status": issue.get("status"),
        "priority": issue.get("priority"),
        "due_date": issue.get("due_date"),
        "recommendations": stored,
    }


def list_requirements(limit: int) -> list[dict[str, Any]]:
    return get_rows(
        "req_code_mapping",
        "issue_id,title,status,priority,due_date",
        order="updated_at.desc",
        limit=limit,
    )


def hydrate_recommendation_list(requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for requirement in requirements:
        issue_id = str(requirement.get("issue_id") or "").strip()
        if not issue_id:
            continue
        stored = get_stored_recommendations(issue_id)
        if not stored:
            recalculated = calculate_and_store_recommendations(issue_id)
            recommendations = recalculated.get("recommendations") or []
        else:
            recommendations = stored

        results.append(
            {
                "requirement_id": issue_id,
                "title": requirement.get("title"),
                "status": requirement.get("status"),
                "priority": requirement.get("priority"),
                "due_date": requirement.get("due_date"),
                "top_score": recommendations[0].get("score") if recommendations else 0,
                "recommendations": recommendations,
            }
        )
    results.sort(key=lambda item: float(item.get("top_score") or 0), reverse=True)
    return results


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "developer-assignment-engine",
        "engine_version": ENGINE_VERSION,
    }


@app.get("/api/developers")
def list_developers(limit: int = 50) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit), 200))
    return {"developers": get_developers(limit=safe_limit)}


@app.post("/api/developers")
def create_or_update_developer(payload: DeveloperPayload) -> dict[str, Any]:
    record = {
        "developer_id": payload.developer_id.strip(),
        "name": payload.name.strip(),
        "email": payload.email.strip() if payload.email else None,
        "age": payload.age,
        "role": payload.role.strip() if payload.role else None,
        "experience_years": round(float(payload.experience_years), 1),
        "seniority_level": payload.seniority_level.strip() if payload.seniority_level else "mid",
        "tech_stack": [str(item).strip() for item in payload.tech_stack if str(item).strip()],
        "summary": payload.summary.strip() if payload.summary else None,
        "current_capacity": max(int(payload.current_capacity), 1),
        "active": bool(payload.active),
    }
    response = upsert_rows("developers", [record], on_conflict="developer_id")
    if isinstance(response, list) and response:
        return response[0]
    return record


@app.delete("/api/developers/{developer_id}")
def delete_developer(developer_id: str) -> dict[str, Any]:
    normalized = developer_id.strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="developer_id is required")

    delete_rows("requirement_developer_recommendations", f"developer_id=eq.{parse.quote(normalized)}")
    delete_rows("developers", f"developer_id=eq.{parse.quote(normalized)}")
    return {"status": "deleted", "developer_id": normalized}


@app.get("/api/assignment/requirement/{issue_id}")
def get_requirement_assignment(issue_id: str, refresh: bool = False) -> dict[str, Any]:
    if refresh:
        return calculate_and_store_recommendations(issue_id)

    requirement = get_requirement(issue_id)
    stored = get_stored_recommendations(issue_id)
    if stored:
        return {
            "requirement_id": requirement.get("issue_id"),
            "title": requirement.get("title"),
            "status": requirement.get("status"),
            "priority": requirement.get("priority"),
            "due_date": requirement.get("due_date"),
            "recommendations": stored,
        }
    return calculate_and_store_recommendations(issue_id)


@app.get("/api/assignment/requirements")
def list_assignment_recommendations(limit: int = 12, refresh: bool = False) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit), 50))
    requirements = list_requirements(limit=safe_limit)
    if refresh:
        rows = []
        for requirement in requirements:
            issue_id = str(requirement.get("issue_id") or "").strip()
            if not issue_id:
                continue
            rows.append(calculate_and_store_recommendations(issue_id))
        rows.sort(key=lambda item: float((item.get("recommendations") or [{}])[0].get("score", 0) if item.get("recommendations") else 0), reverse=True)
        return {"requirements": rows}

    return {"requirements": hydrate_recommendation_list(requirements)}


@app.post("/api/assignment/recalculate/{issue_id}")
def recalculate_single_assignment(issue_id: str) -> dict[str, Any]:
    return calculate_and_store_recommendations(issue_id)


@app.post("/api/assignment/recalculate")
def recalculate_assignments(limit: int = 25) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit), 100))
    requirements = list_requirements(limit=safe_limit)
    rows = []
    for requirement in requirements:
        issue_id = str(requirement.get("issue_id") or "").strip()
        if not issue_id:
            continue
        rows.append(calculate_and_store_recommendations(issue_id))
    rows.sort(key=lambda item: float((item.get("recommendations") or [{}])[0].get("score", 0) if item.get("recommendations") else 0), reverse=True)
    return {"requirements": rows}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8004")), reload=True)
