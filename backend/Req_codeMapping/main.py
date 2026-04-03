import json
import math
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional
from urllib import error, parse, request

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
import asyncio

import utils


ROOT_DIR = Path(__file__).resolve().parent
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL") or os.getenv("VITE_SUPABASE_URL")
SUPABASE_API_KEY = (
    os.getenv("SUPABASE_SERVICE_KEY")
    or os.getenv("SUPABASE_ANON_KEY")
    or os.getenv("VITE_SUPABASE_ANON_KEY")
)
BASE_REST_URL = f"{(SUPABASE_URL or '').rstrip('/')}/rest/v1"

FASTEMBED_MODEL_NAME = os.getenv("REQ_MATCH_MODEL", "BAAI/bge-small-en-v1.5")
MATCH_THRESHOLD = float(os.getenv("REQ_MATCH_THRESHOLD", "0.45"))
AUTO_SYNC_ON_DASHBOARD = os.getenv("AUTO_SYNC_ON_DASHBOARD", "false").strip().lower() == "true"
MAX_PATCH_CHARS = int(os.getenv("REQ_MATCH_MAX_PATCH_CHARS", "4000"))
MAX_COMMIT_TEXT_CHARS = int(os.getenv("REQ_MATCH_MAX_COMMIT_TEXT_CHARS", "12000"))

if not SUPABASE_URL or not SUPABASE_API_KEY:
    print("WARNING: Missing Supabase credentials! The service will not be able to sync.")

DEFAULT_HEADERS = {
    "apikey": SUPABASE_API_KEY,
    "Authorization": f"Bearer {SUPABASE_API_KEY}",
}

app = FastAPI(title="Supabase Commit Sync API")


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(fallback_loop())


async def fallback_loop():
    while True:
        try:
            print("[INFO] Running fallback queue check...")
            process_unmapped_queue()
        except Exception as e:
            print(f"Fallback queue error: {e}")
        await asyncio.sleep(600)  # Wait 10 minutes between loops


def parse_allowed_origins() -> list[str]:
    configured = os.getenv("ALLOWED_ORIGINS", "")
    parsed = [origin.strip().rstrip("/") for origin in configured.split(",") if origin.strip()]

    frontend_url = (os.getenv("FRONTEND_URL") or "http://localhost:5173").rstrip("/")
    default_origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        frontend_url,
    ]

    seen: set[str] = set()
    origins: list[str] = []
    for origin in [*default_origins, *parsed]:
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


@lru_cache(maxsize=1)
def get_embedder():
    from fastembed import TextEmbedding
    # threads=1 strictly reduces memory footprint ensuring it stays within 512MB RAM free tier
    return TextEmbedding(model_name=FASTEMBED_MODEL_NAME, threads=1)


def embed_texts(texts: list[str]) -> list[list[float]]:
    cleaned = [normalize_spaces(text) for text in texts]
    if not cleaned:
        return []
    embeddings = list(get_embedder().embed(cleaned))
    return [[float(value) for value in vector.tolist()] for vector in embeddings]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return numerator / (left_norm * right_norm)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/dashboard")
def dashboard() -> dict[str, Any]:
    issues = get_rows(
        "req_code_mapping",
        "issue_id,title,status,issue_type,priority,project_key,assignee_email,reporter_email,commits,created_at,updated_at",
        order="updated_at.desc",
        limit=100,
    )
    events = get_rows(
        "extension_events",
        "id,event_type,developer_id,repository_name,timestamp,commit_id,branch,message,issue_id,additions,deletions,total_changes,author,author_email,attendance_pct",
        order="timestamp.desc",
        limit=100,
    )

    sync_result = summarize_current_links(issues)
    if AUTO_SYNC_ON_DASHBOARD:
        try:
            sync_result = sync_commit_links()
        except HTTPException as exc:
            sync_result = {
                **sync_result,
                "warning": f"Auto-sync skipped: {exc.detail}",
            }

    return {"sync": sync_result, "issues": issues, "events": events}


@app.post("/api/sync")
def sync_endpoint() -> dict[str, Any]:
    # Hard-blocking bulk syncs. They consume hundreds of MBs of RAM and OOM Free Tiers.
    # The new Database queue architecture handles everything sequentially anyway!
    return {"status": "disabled", "message": "Bulk sync is disabled to protect RAM constraints. Queue handles all syncs natively."}


@app.post("/api/match-commit")
def match_commit_endpoint(bg_tasks: BackgroundTasks) -> dict[str, Any]:
    bg_tasks.add_task(process_unmapped_queue)
    return {"status": "queued_processing"}


@app.post("/api/extension-events/webhook")
def extension_events_webhook(payload: dict[str, Any], bg_tasks: BackgroundTasks) -> dict[str, Any]:
    event_type = str(payload.get("type") or payload.get("eventType") or payload.get("event_type") or "").lower()
    
    # 1. Handle Deletions
    if "delete" in event_type:
        old_record = payload.get("old_record") or payload.get("record") or payload.get("data") or {}
        commit_id = str(old_record.get("commit_id") or "").strip()
        if not commit_id:
            commit_id = str(payload.get("commit_id") or "").strip()
            
        if commit_id:
            bg_tasks.add_task(process_commit_deletion, commit_id)
            return {"status": "queued_deletion", "commit_id": commit_id}
        return {"status": "ignored", "reason": "missing_commit_id_in_delete"}

    # 2. For any insert/create, spin up the queue processor implicitly!
    bg_tasks.add_task(process_unmapped_queue)
    return {"status": "queued_processing"}

def process_commit_deletion(commit_id: str) -> dict[str, Any]:
    """Handles the cascading deletion of a commit from mapping tables."""
    try:
        # We don't delete from extension_events (telemetry), but we remove the commit mapping
        request_json("POST", f"{BASE_REST_URL}/rpc/remove_commit_from_all_requirements", payload={
            "p_commit_id": commit_id
        })
        
        return {"status": "deleted", "commit_id": commit_id}
    except Exception as e:
        print(f"Error during deletion sync for {commit_id}: {e}")
        # Not raising 500 so webhook doesn't spam retry, just returning
        return {"status": "error", "commit_id": commit_id, "detail": str(e)}


def sync_commit_links() -> dict[str, Any]:
    issues = fetch_issues()
    events = fetch_events()
    valid_event_commit_ids = {
        str(event.get("commit_id"))
        for event in events
        if event.get("commit_id") is not None and str(event.get("commit_id")).strip()
    }

    issue_to_commits: dict[str, list[str]] = {str(issue["issue_id"]): [] for issue in issues}
    issue_to_matches: dict[str, list[dict[str, Any]]] = {str(issue["issue_id"]): [] for issue in issues}

    commit_rows = []
    for event in events:
        commit_id = str(event.get("commit_id") or "").strip()
        commit_text = build_commit_text(event)
        if commit_id and commit_text:
            commit_rows.append({"commit_id": commit_id, "text": commit_text})

    match_results = match_commit_rows(commit_rows, issues)
    for result in match_results:
        if not result.get("issue_id"):
            continue
        issue_id = str(result["issue_id"])
        issue_to_commits[issue_id].append(str(result["commit_id"]))
        issue_to_matches[issue_id].append(
            {
                "commit_id": str(result["commit_id"]),
                "score": round(float(result["score"]), 4),
                "reasons": [
                    f"fastembed cosine similarity via {FASTEMBED_MODEL_NAME}",
                    f"threshold {MATCH_THRESHOLD:.2f}",
                ],
            }
        )

    updates: list[dict[str, Any]] = []
    matched_issue_count = 0
    total_linked_commits = 0

    for issue in issues:
        issue_id = str(issue["issue_id"])
        matched_commit_ids = dedupe_preserve_order(issue_to_commits[issue_id])
        existing = [
            str(commit_id)
            for commit_id in (issue.get("commits") or [])
            if commit_id is not None and str(commit_id).strip() and str(commit_id) in valid_event_commit_ids
        ]

        if sorted(matched_commit_ids) != sorted(existing):
            patch_row(
                "req_code_mapping",
                f"issue_id=eq.{parse.quote(issue_id)}",
                {"commits": matched_commit_ids},
            )

        if matched_commit_ids:
            matched_issue_count += 1
            total_linked_commits += len(matched_commit_ids)

        updates.append(
            {
                "issue_id": issue_id,
                "commits": matched_commit_ids,
                "matches": issue_to_matches[issue_id],
            }
        )

    return {
        "updated_issues": len(updates),
        "matched_issues": matched_issue_count,
        "linked_commits": total_linked_commits,
        "updates": updates,
    }


def process_unmapped_queue() -> None:
    """Pulls all unprocessed rows from extension_events and processes them sequentially."""
    print("[INFO] Waking up background queue processor...")
    try:
        # Fetch up to 50 unprocessed commits
        unprocessed = request_json("GET", f"{BASE_REST_URL}/extension_events?processed=eq.false&limit=50")
        if not isinstance(unprocessed, list) or len(unprocessed) == 0:
            return
            
        print(f"[INFO] Found {len(unprocessed)} unprocessed commits.")
        
        for event in unprocessed:
            commit_id = str(event.get("commit_id") or "").strip()
            if not commit_id:
                continue
                
            message = str(event.get("message") or "").strip().lower()
            
            # Check 1: Ignore trivial or noise commits
            trivial_keywords = ["initial commit", "init", "wip", "update", "dummy", "test", "fix"]
            if message in trivial_keywords or len(message) < 5:
                mark_commit_processed(commit_id, store_embedding=False)
                continue

            commit_context = utils.build_commit_context(event)
            if not commit_context:
                mark_commit_processed(commit_id, store_embedding=False)
                continue

            # Step 2: Embed context
            embeddings = embed_texts([commit_context])
            if not embeddings:
                mark_commit_processed(commit_id, store_embedding=False)
                continue
                
            commit_embedding = embeddings[0]
            
            # Step 3: IN PLACE UPDATE -> patch "extension_events"
            try:
                patch_row(
                    "extension_events",
                    f"commit_id=eq.{parse.quote(commit_id)}",
                    {
                        "embedding": commit_embedding,
                        "embeddings_stored": True
                    }
                )
            except Exception as e:
                print(f"Failed to update embedding for {commit_id}: {e}")
                continue

            # Step 4: Call Supabase native similarity search RPC
            candidates = request_json("POST", f"{BASE_REST_URL}/rpc/match_requirements", payload={
                "query_embedding": commit_embedding,
                "match_threshold": 0.35,
                "match_count": 6
            })

            if not candidates:
                mark_commit_processed(commit_id, store_embedding=True)
                continue

            # Step 5: Smart Re-ranking in Python
            best_match = utils.re_rank_candidates(candidates, event)

            if best_match and best_match.get("confidence", 0) >= 0.55:
                issue_id = best_match["issue_id"]
                
                commit_payload = {
                    "commit_id": commit_id,
                    "message": event.get("message"),
                    "timestamp": event.get("timestamp"),
                    "author": event.get("author"),
                    "confidence": round(best_match["confidence"], 4)
                }
                
                request_json("POST", f"{BASE_REST_URL}/rpc/append_commit_to_requirement", payload={
                    "p_issue_id": issue_id,
                    "p_commit_data": commit_payload
                })
                
            mark_commit_processed(commit_id, store_embedding=True)
            
    except Exception as e:
        print(f"[ERROR] Queue processor failed: {e}")


def mark_commit_processed(commit_id: str, store_embedding: bool = False) -> None:
    """Marks a commit as safely completed so the loop won't pick it up again."""
    if not commit_id:
        return
    try:
        patch_query = f"commit_id=eq.{parse.quote(commit_id)}"
        patch_row("extension_events", patch_query, {"processed": True, "embeddings_stored": store_embedding})
    except Exception as e:
        print(f"Failed to mark processed for {commit_id}: {e}")


def fetch_issues() -> list[dict[str, Any]]:
    return get_rows(
        "req_code_mapping",
        "issue_id,title,description,commits",
        order="created_at.asc",
        limit=500,
    )


def fetch_events() -> list[dict[str, Any]]:
    return get_rows(
        "extension_events",
        "commit_id,message,timestamp,files,files_json,diff_patch,repository_name,branch",
        order="timestamp.asc",
        limit=500,
    )


def match_commit_rows(commit_rows: list[dict[str, str]], issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issue_rows = [
        {"issue_id": str(issue.get("issue_id") or "").strip(), "text": build_requirement_text(issue)}
        for issue in issues
    ]
    issue_rows = [issue for issue in issue_rows if issue["issue_id"] and issue["text"]]
    if not issue_rows or not commit_rows:
        return []

    issue_embeddings = embed_texts([f"passage: {issue['text']}" for issue in issue_rows])
    commit_embeddings = embed_texts([f"query: {commit['text']}" for commit in commit_rows])
    results: list[dict[str, Any]] = []

    for commit_row, commit_embedding in zip(commit_rows, commit_embeddings):
        best_issue_id = None
        best_score = -1.0

        for issue_row, issue_embedding in zip(issue_rows, issue_embeddings):
            score = cosine_similarity(commit_embedding, issue_embedding)
            if score > best_score:
                best_score = score
                best_issue_id = issue_row["issue_id"]

        if best_issue_id and best_score >= MATCH_THRESHOLD:
            results.append(
                {
                    "commit_id": commit_row["commit_id"],
                    "issue_id": best_issue_id,
                    "score": best_score,
                }
            )
        else:
            results.append(
                {
                    "commit_id": commit_row["commit_id"],
                    "issue_id": None,
                    "score": best_score,
                }
            )

    return results


def update_commit_mapping(commit_id: str, match: Optional[dict[str, Any]], issues: list[dict[str, Any]]) -> None:
    target_issue_id = str(match.get("issue_id") or "") if match else ""

    for issue in issues:
        issue_id = str(issue.get("issue_id") or "")
        existing = [str(value) for value in (issue.get("commits") or []) if str(value).strip()]

        if issue_id == target_issue_id:
            updated = dedupe_preserve_order([*existing, commit_id])
        else:
            updated = [value for value in existing if value != commit_id]

        if updated != existing:
            patch_row(
                "req_code_mapping",
                f"issue_id=eq.{parse.quote(issue_id)}",
                {"commits": updated},
            )


def extract_event_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid payload")

    for key in ("record", "new", "data"):
        candidate = payload.get(key)
        if isinstance(candidate, dict) and candidate.get("commit_id"):
            return candidate

    if payload.get("commit_id"):
        return payload

    raise HTTPException(status_code=400, detail="No commit record found in payload")


def summarize_current_links(issues: list[dict[str, Any]]) -> dict[str, Any]:
    matched_issues = 0
    linked_commits = 0

    for issue in issues:
        commits = issue.get("commits") or []
        if commits:
            matched_issues += 1
            linked_commits += len(commits)

    return {
        "updated_issues": 0,
        "matched_issues": matched_issues,
        "linked_commits": linked_commits,
        "updates": [],
    }


def build_requirement_text(issue: dict[str, Any]) -> str:
    parts = [
        str(issue.get("issue_id") or ""),
        str(issue.get("title") or ""),
        str(issue.get("description") or ""),
    ]
    return normalize_spaces(" ".join(parts))


def build_commit_text(event: dict[str, Any]) -> str:
    files = extract_event_files(event)
    segments = [str(event.get("message") or "").strip()]

    for file in files:
        file_path = str(file.get("file_path") or "").strip()
        patch = str(file.get("patch") or "").strip()
        if patch:
            patch = patch[:MAX_PATCH_CHARS]
        piece = normalize_spaces(" ".join(part for part in [file_path, patch] if part))
        if piece:
            segments.append(piece)

    diff_patch = str(event.get("diff_patch") or "").strip()
    if diff_patch:
        segments.append(diff_patch[:MAX_PATCH_CHARS])

    return normalize_spaces(" ".join(segments))[:MAX_COMMIT_TEXT_CHARS]


def extract_event_files(event: dict[str, Any]) -> list[dict[str, Any]]:
    direct_files = event.get("files")
    if isinstance(direct_files, list):
        return [file for file in direct_files if isinstance(file, dict)]

    files_json = event.get("files_json")
    if isinstance(files_json, dict):
        nested_files = files_json.get("files")
        if isinstance(nested_files, list):
            return [file for file in nested_files if isinstance(file, dict)]
    if isinstance(files_json, list):
        return [file for file in files_json if isinstance(file, dict)]

    return []


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def normalize_spaces(text: str) -> str:
    return " ".join(str(text or "").split())


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


def patch_row(table: str, filters: str, payload: dict[str, Any]) -> Any:
    headers = {
        **DEFAULT_HEADERS,
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    return request_json("PATCH", f"{BASE_REST_URL}/{table}?{filters}", payload=payload, headers=headers)


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
