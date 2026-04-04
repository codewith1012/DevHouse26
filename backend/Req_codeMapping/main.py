import asyncio
import json
import os
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional
from urllib import error, parse, request

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from utils import (
    build_commit_context,
    normalize_spaces,
    re_rank_candidates,
    should_skip_commit,
    cosine_similarity,
)

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
MATCH_THRESHOLD = float(os.getenv("REQ_MATCH_THRESHOLD", "0.35"))
COMMIT_MAP_THRESHOLD = float(os.getenv("COMMIT_MAP_THRESHOLD", "0.55"))
BOOSTED_MAP_THRESHOLD = float(os.getenv("BOOSTED_MAP_THRESHOLD", "0.52"))
LOW_CONFIDENCE_BAND = float(os.getenv("LOW_CONFIDENCE_BAND", "0.42"))
MATCH_CANDIDATE_COUNT = int(os.getenv("MATCH_CANDIDATE_COUNT", "15"))
AUTO_SYNC_ON_DASHBOARD = os.getenv("AUTO_SYNC_ON_DASHBOARD", "false").strip().lower() == "true"
MAX_PATCH_CHARS = int(os.getenv("REQ_MATCH_MAX_PATCH_CHARS", "4000"))
MAX_COMMIT_TEXT_CHARS = int(os.getenv("REQ_MATCH_MAX_COMMIT_TEXT_CHARS", "12000"))

if not SUPABASE_URL or not SUPABASE_API_KEY:
    print("WARNING: Missing Supabase credentials! The service will not be able to sync.")

DEFAULT_HEADERS = {
    "apikey": SUPABASE_API_KEY,
    "Authorization": f"Bearer {SUPABASE_API_KEY}",
}

APP_STATE: dict[str, Any] = {
    "model_loaded": False,
    "model_load_seconds": None,
    "last_requirements_processed": 0,
    "last_commits_processed": 0,
    "last_issue_id": None,
    "last_commit_id": None,
    "last_queue_run_at": None,
}

JIRA_KEY_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")

app = FastAPI(title="Supabase Commit Sync API")


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


def warm_embedding_model() -> None:
    print(f"[INFO] Downloading/loading embedding model {FASTEMBED_MODEL_NAME} ...")
    started = time.perf_counter()
    get_embedder()
    elapsed = round(time.perf_counter() - started, 2)
    APP_STATE["model_loaded"] = True
    APP_STATE["model_load_seconds"] = elapsed
    print(f"[INFO] Embedding model loaded successfully! (took {elapsed} seconds)")


def embed_texts(texts: list[str]) -> list[list[float]]:
    cleaned = [normalize_spaces(text) for text in texts if normalize_spaces(text)]
    if not cleaned:
        return []
    embeddings = list(get_embedder().embed(cleaned))
    return [[float(value) for value in vector.tolist()] for vector in embeddings]


@app.on_event("startup")
async def startup_event() -> None:
    try:
        warm_embedding_model()
    except Exception as exc:
        print(f"[ERROR] Failed to load embedding model: {exc}")
        return

    # Small pause improves startup log readability and avoids immediate resource spikes.
    await asyncio.sleep(0.5)

    # Only after successful model load do we start queue/embedding processors.
    asyncio.create_task(initial_bootstrap_processing())
    asyncio.create_task(fallback_loop())


async def initial_bootstrap_processing() -> None:
    req_count = await asyncio.to_thread(embed_missing_requirements)
    APP_STATE["last_requirements_processed"] = req_count
    print(f"[INFO] Initial Jira requirements embedding completed. Processed {req_count} issues.")

    commit_count = await process_unmapped_queue()
    APP_STATE["last_commits_processed"] = commit_count


async def fallback_loop() -> None:
    while True:
        try:
            req_count = await asyncio.to_thread(embed_missing_requirements)
            APP_STATE["last_requirements_processed"] = req_count
            commit_count = await process_unmapped_queue()
            APP_STATE["last_commits_processed"] = commit_count
        except Exception as exc:
            print(f"[ERROR] Fallback queue error: {exc}")
        await asyncio.sleep(30)


@app.get("/api/health")
def health() -> dict[str, Any]:
    requirements_without_embeddings = count_rows(
        "req_code_mapping",
        "issue_id",
        "embedding=is.null",
    )
    unmapped_commits = count_rows(
        "extension_events",
        "commit_id",
        "or=(processed.eq.false,embeddings_stored.eq.false,embedding.is.null)",
    )
    return {
        "status": "ok",
        "model": FASTEMBED_MODEL_NAME,
        "match_threshold": MATCH_THRESHOLD,
        "map_threshold": COMMIT_MAP_THRESHOLD,
        "boosted_map_threshold": BOOSTED_MAP_THRESHOLD,
        "model_loaded": APP_STATE["model_loaded"],
        "model_load_seconds": APP_STATE["model_load_seconds"],
        "last_requirements_processed": APP_STATE["last_requirements_processed"],
        "last_commits_processed": APP_STATE["last_commits_processed"],
        "last_issue_id": APP_STATE["last_issue_id"],
        "last_commit_id": APP_STATE["last_commit_id"],
        "last_queue_run_at": APP_STATE["last_queue_run_at"],
        "requirements_without_embeddings": requirements_without_embeddings,
        "unmapped_commits": unmapped_commits,
    }


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
            sync_result = {**sync_result, "warning": f"Auto-sync skipped: {exc.detail}"}

    return {"sync": sync_result, "issues": issues, "events": events}


@app.post("/api/sync")
def sync_endpoint() -> dict[str, Any]:
    return {
        "status": "disabled",
        "message": "Bulk sync is disabled to protect RAM constraints. Queue handles all syncs natively.",
    }


@app.post("/api/match-commit")
def match_commit_endpoint(bg_tasks: BackgroundTasks) -> dict[str, Any]:
    bg_tasks.add_task(process_unmapped_queue)
    return {"status": "queued_processing"}


@app.post("/api/embed-requirements")
def embed_requirements_endpoint(bg_tasks: BackgroundTasks) -> dict[str, Any]:
    bg_tasks.add_task(embed_missing_requirements)
    return {"status": "queued", "message": "Embedding requirements in background. Watch logs for progress."}


@app.post("/api/jira-webhook")
def jira_webhook(payload: dict[str, Any], bg_tasks: BackgroundTasks) -> dict[str, Any]:
    webhook_event = str(payload.get("webhookEvent") or "").lower()
    issue = payload.get("issue") or {}
    issue_id = str(issue.get("key") or payload.get("issue_key") or payload.get("issueKey") or "").strip()

    if "delete" in webhook_event:
        bg_tasks.add_task(process_jira_issue_delete, issue_id)
        return {"status": "accepted", "action": "delete_queued", "issue_id": issue_id}

    if not issue:
        return {"status": "ignored", "reason": "no_issue_payload"}

    bg_tasks.add_task(process_jira_issue_upsert, issue)
    return {"status": "accepted", "action": "upsert_queued", "issue_id": issue_id}


@app.post("/api/extension-events/webhook")
def extension_events_webhook(payload: dict[str, Any], bg_tasks: BackgroundTasks) -> dict[str, Any]:
    event_type = str(payload.get("type") or payload.get("eventType") or payload.get("event_type") or "").lower()

    if "delete" in event_type:
        old_record = payload.get("old_record") or payload.get("record") or payload.get("data") or {}
        commit_id = str(old_record.get("commit_id") or "").strip() or str(payload.get("commit_id") or "").strip()
        if commit_id:
            bg_tasks.add_task(process_commit_deletion, commit_id)
            return {"status": "queued_deletion", "commit_id": commit_id}
        return {"status": "ignored", "reason": "missing_commit_id_in_delete"}

    try:
        event = extract_event_from_payload(payload)
        commit_id = str(event.get("commit_id") or "").strip()
        if commit_id:
            # Process this commit immediately for fast mapping.
            bg_tasks.add_task(process_single_commit, commit_id, event)
            return {"status": "queued_processing", "commit_id": commit_id}
    except Exception as exc:
        print(f"[INFO] Webhook payload missing explicit commit_id: {exc}")

    # Fallback: wake up queue only when commit_id could not be extracted.
    bg_tasks.add_task(process_unmapped_queue)
    return {"status": "queued_processing"}


def parse_adf_to_text(adf: Any) -> str:
    if not adf:
        return ""
    if isinstance(adf, str):
        return adf

    text_parts: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, str):
            text_parts.append(node)
            return
        if not isinstance(node, dict):
            return
        if node.get("type") == "text":
            text_parts.append(str(node.get("text") or ""))
        content = node.get("content")
        if isinstance(content, list):
            for child in content:
                walk(child)

    walk(adf)
    return normalize_spaces(" ".join(text_parts))


def build_requirement_text(issue: dict[str, Any]) -> str:
    parts = [
        str(issue.get("issue_id") or ""),
        str(issue.get("title") or ""),
        str(issue.get("description") or ""),
    ]
    return normalize_spaces(" ".join(parts))


def build_jira_record(issue: dict[str, Any]) -> dict[str, Any]:
    fields = issue.get("fields") or {}
    issue_id = str(issue.get("key") or "").strip()
    title = str(fields.get("summary") or "").strip()
    description = parse_adf_to_text(fields.get("description"))

    requirement_text = normalize_spaces(f"{issue_id} {title} {description}")
    vectors = embed_texts([f"passage: {requirement_text}"])
    embedding = vectors[0] if vectors else None

    record: dict[str, Any] = {
        "issue_id": issue_id,
        "title": title,
        "description": description,
        "status": fields.get("status", {}).get("name"),
        "issue_type": fields.get("issuetype", {}).get("name"),
        "priority": fields.get("priority", {}).get("name"),
        "project_key": fields.get("project", {}).get("key"),
        "assignee_email": fields.get("assignee", {}).get("emailAddress") if fields.get("assignee") else None,
        "reporter_email": fields.get("reporter", {}).get("emailAddress") if fields.get("reporter") else None,
        "jira_created_at": fields.get("created"),
        "jira_updated_at": fields.get("updated"),
    }
    if embedding:
        record["embedding"] = embedding
    return record


def process_jira_issue_upsert(issue: dict[str, Any]) -> None:
    try:
        record = build_jira_record(issue)
        issue_id = str(record.get("issue_id") or "").strip()
        if not issue_id:
            print("[JIRA] Ignored payload without issue key")
            return

        upsert_row("req_code_mapping", record, on_conflict="issue_id")
        APP_STATE["last_issue_id"] = issue_id
        action = "Updated/Created"
        print(f"[JIRA] Processed issue {issue_id} ({action}) - Embedding stored")
    except Exception as exc:
        issue_id = str(issue.get("key") or "unknown")
        print(f"[JIRA] Failed processing issue {issue_id}: {exc}")


def process_jira_issue_delete(issue_id: str) -> None:
    if not issue_id:
        print("[JIRA] Delete ignored: missing issue_id")
        return
    try:
        delete_rows("req_code_mapping", f"issue_id=eq.{parse.quote(issue_id)}")
        # Clean direct links on telemetry rows if the column exists.
        try:
            patch_row("extension_events", f"issue_id=eq.{parse.quote(issue_id)}", {"issue_id": None})
        except Exception:
            pass
        APP_STATE["last_issue_id"] = issue_id
        print(f"[JIRA] Deleted issue {issue_id} and cleaned linked commit references")
    except Exception as exc:
        print(f"[JIRA] Failed to delete issue {issue_id}: {exc}")


def fetch_requirements_missing_embeddings(limit: int = 50) -> list[dict[str, Any]]:
    base_select = "issue_id,title,description,status,issue_type,priority,jira_updated_at,embedding"

    # Try flexible filter first for schemas that include embeddings_stored.
    query_with_flag = (
        f"select={base_select}"
        "&or=(embedding.is.null,embeddings_stored.eq.false)"
        "&order=jira_updated_at.asc"
        f"&limit={limit}"
    )
    try:
        response = request_json("GET", f"{BASE_REST_URL}/req_code_mapping?{query_with_flag}")
        return response if isinstance(response, list) else []
    except HTTPException:
        # Fallback for schemas without embeddings_stored column.
        pass

    params = {
        "select": base_select,
        "embedding": "is.null",
        "order": "jira_updated_at.asc",
        "limit": str(limit),
    }
    query = parse.urlencode(params, safe="*,()")
    response = request_json("GET", f"{BASE_REST_URL}/req_code_mapping?{query}")
    return response if isinstance(response, list) else []


def embed_missing_requirements(batch_size: int = 25, max_batches: int = 20) -> int:
    processed = 0
    batches = 0

    while batches < max_batches:
        batches += 1
        rows = fetch_requirements_missing_embeddings(limit=batch_size)
        if not rows:
            break

        for row in rows:
            issue_id = str(row.get("issue_id") or "").strip()
            if not issue_id:
                continue
            text = build_requirement_text(row)
            if not text:
                continue

            try:
                vectors = embed_texts([f"passage: {text}"])
                if not vectors:
                    print(f"[JIRA] Failed to embed requirement {issue_id}: empty vector")
                    continue
                patch_row(
                    "req_code_mapping",
                    f"issue_id=eq.{parse.quote(issue_id)}",
                    {"embedding": vectors[0]},
                )
                processed += 1
                APP_STATE["last_issue_id"] = issue_id
            except Exception as exc:
                print(f"[JIRA] Failed to embed requirement {issue_id}: {exc}")

    return processed


def process_commit_deletion(commit_id: str) -> dict[str, Any]:
    try:
        request_json("POST", f"{BASE_REST_URL}/rpc/remove_commit_from_all_requirements", payload={"p_commit_id": commit_id})
        return {"status": "deleted", "commit_id": commit_id}
    except Exception as exc:
        print(f"Error during deletion sync for {commit_id}: {exc}")
        return {"status": "error", "commit_id": commit_id, "detail": str(exc)}


async def process_single_commit(commit_id: str, event: Optional[dict[str, Any]] = None) -> None:
    await asyncio.to_thread(_process_single_commit_sync, commit_id, event)


def _process_single_commit_sync(commit_id: str, event: Optional[dict[str, Any]] = None) -> None:
    store_embedding: Optional[bool] = None
    processed_done = False
    try:
        if not event:
            events = request_json(
                "GET",
                f"{BASE_REST_URL}/extension_events?commit_id=eq.{parse.quote(commit_id)}&limit=1",
            )
            if not events or not isinstance(events, list):
                print(f"[COMMIT] Processed {commit_id} -> No strong match found (best confidence: 0.000)")
                return
            event = events[0]

        message = str(event.get("message") or "").strip()

        if should_skip_commit(message, event):
            store_embedding = True
            processed_done = True
            print(f"[COMMIT] Processed {commit_id} -> Skipped noise commit")
            return

        commit_context = build_commit_context(event)
        if not commit_context:
            store_embedding = True
            processed_done = True
            print(f"[COMMIT] Processed {commit_id} -> Skipped noise commit")
            return

        embeddings = embed_texts([f"query: {commit_context}"])
        if not embeddings:
            store_embedding = False
            processed_done = False
            print(f"[COMMIT] Processed {commit_id} -> No strong match found (best confidence: 0.000)")
            return

        commit_embedding = embeddings[0]
        patch_row(
            "extension_events",
            f"commit_id=eq.{parse.quote(commit_id)}",
            {"embedding": commit_embedding, "embeddings_stored": True},
        )
        store_embedding = True
        processed_done = True
        print(f"[COMMIT] Embedded {commit_id} (length: {len(commit_embedding)}). Attempting requirement match...")

        # Key-first mapping for highest precision when explicit Jira key is present.
        direct_issue_id = _resolve_direct_issue_id(event)
        if direct_issue_id and _requirement_exists(direct_issue_id):
            _apply_commit_mapping(commit_id, event, direct_issue_id, confidence=1.0, source="direct-key")
            APP_STATE["last_commit_id"] = commit_id
            print(f"[COMMIT] Processed {commit_id} -> Mapped to {direct_issue_id} (direct key match)")
            return

        # Semantic mapping: top-k cosine retrieval then heuristic re-rank.
        candidates = _cosine_match_requirements(commit_embedding, top_k=MATCH_CANDIDATE_COUNT)

        best_match = re_rank_candidates(candidates or [], event)
        best_conf = float(best_match.get("confidence", 0.0)) if best_match else 0.0

        dynamic_threshold = COMMIT_MAP_THRESHOLD
        if best_match and float(best_match.get("boost", 0.0)) > 0:
            dynamic_threshold = BOOSTED_MAP_THRESHOLD

        if best_match and best_match.get("issue_id") and best_conf >= dynamic_threshold:
            issue_id = str(best_match["issue_id"])
            _apply_commit_mapping(commit_id, event, issue_id, confidence=best_conf, source="semantic")
            APP_STATE["last_commit_id"] = commit_id
            processed_done = True
            print(
                f"[COMMIT] Processed {commit_id} -> Mapped to {issue_id} "
                f"(Confidence: {best_conf:.3f}, threshold: {dynamic_threshold:.3f})"
            )
        elif best_match and best_match.get("issue_id") and best_conf >= LOW_CONFIDENCE_BAND:
            # MVP bias: allow cautious mapping in low-confidence band.
            issue_id = str(best_match["issue_id"])
            _apply_commit_mapping(commit_id, event, issue_id, confidence=best_conf, source="low-confidence-band")
            APP_STATE["last_commit_id"] = commit_id
            processed_done = True
            print(
                f"[COMMIT] Processed {commit_id} -> Mapped to {issue_id} "
                f"(Low confidence: {best_conf:.3f}, band: {LOW_CONFIDENCE_BAND:.3f})"
            )
        else:
            patch_row(
                "extension_events",
                f"commit_id=eq.{parse.quote(commit_id)}",
                {"issue_id": None},
            )
            processed_done = True
            print(
                f"[COMMIT] Processed {commit_id} -> No strong match found "
                f"(best confidence: {best_conf:.3f}, threshold: {dynamic_threshold:.3f})"
            )

    except Exception as exc:
        processed_done = False
        print(f"[ERROR] Exception processing commit {commit_id}: {exc}")
    finally:
        mark_commit_processed(
            commit_id,
            store_embedding=store_embedding,
            processed=processed_done,
        )


async def process_unmapped_queue() -> int:
    print("[INFO] Waking up background queue processor...")
    processed_count = 0
    try:
        while True:
            await asyncio.sleep(0.1)
            query = (
                "select=commit_id,message,files,files_json,diff_patch,timestamp,author,branch,pr_title,linked_issue,processed,embeddings_stored"
                "&processed=eq.false"
                "&order=timestamp.asc&limit=50"
            )
            pending = await asyncio.to_thread(request_json, "GET", f"{BASE_REST_URL}/extension_events?{query}")
            if not isinstance(pending, list) or len(pending) == 0:
                print("[INFO] Queue is empty. All commits processed.")
                break

            seen: set[str] = set()
            for event in pending:
                commit_id = str(event.get("commit_id") or "").strip()
                if not commit_id or commit_id in seen:
                    continue
                seen.add(commit_id)
                await process_single_commit(commit_id, event)
                processed_count += 1
                await asyncio.sleep(0.35)

        APP_STATE["last_queue_run_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        return processed_count
    except Exception as exc:
        print(f"[ERROR] Queue processor failed: {exc}")
        APP_STATE["last_queue_run_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        return processed_count


def mark_commit_processed(
    commit_id: str,
    store_embedding: Optional[bool] = None,
    processed: bool = True,
) -> None:
    if not commit_id:
        return
    try:
        patch_query = f"commit_id=eq.{parse.quote(commit_id)}"
        payload: dict[str, Any] = {"processed": processed}
        if store_embedding is not None:
            payload["embeddings_stored"] = bool(store_embedding)
        patch_row("extension_events", patch_query, payload)
    except Exception as exc:
        print(f"Failed to mark processed for {commit_id}: {exc}")


def _fallback_match_requirements(commit_embedding: list[float]) -> list[dict[str, Any]]:
    # Backward compatibility alias.
    return _cosine_match_requirements(commit_embedding)


def _cosine_match_requirements(commit_embedding: list[float], top_k: int = 8) -> list[dict[str, Any]]:
    """
    Computes cosine similarity directly between a commit embedding
    (extension_events.embedding) and requirement embeddings
    (req_code_mapping.embedding), returning top candidates.
    """
    try:
        issues = get_rows(
            "req_code_mapping",
            "issue_id,title,description,embedding",
            order="jira_updated_at.asc",
            limit=1000,
        )
    except Exception as exc:
        print(f"[ERROR] Cosine matcher: Failed to fetch requirements: {exc}")
        return []

    candidates: list[dict[str, Any]] = []
    for issue in issues:
        raw_embedding = issue.get("embedding")
        if not raw_embedding or not isinstance(raw_embedding, list):
            continue
        try:
            issue_embedding = [float(value) for value in raw_embedding]
            sim = cosine_similarity(commit_embedding, issue_embedding)
            if sim >= MATCH_THRESHOLD:
                candidates.append(
                    {
                        "issue_id": issue.get("issue_id"),
                        "title": issue.get("title"),
                        "description": issue.get("description"),
                        "similarity": round(sim, 6),
                    }
                )
        except Exception:
            continue

    candidates.sort(key=lambda value: value["similarity"], reverse=True)
    return candidates[:max(top_k, 1)]


def _extract_jira_keys(*texts: Any) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for raw in texts:
        text = str(raw or "")
        for key in JIRA_KEY_PATTERN.findall(text):
            normalized = key.upper()
            if normalized not in seen:
                seen.add(normalized)
                keys.append(normalized)
    return keys


def _resolve_direct_issue_id(event: dict[str, Any]) -> Optional[str]:
    keys = _extract_jira_keys(
        event.get("message"),
        event.get("branch"),
        event.get("pr_title"),
        event.get("linked_issue"),
    )
    return keys[0] if keys else None


def _requirement_exists(issue_id: str) -> bool:
    if not issue_id:
        return False
    try:
        rows = request_json(
            "GET",
            f"{BASE_REST_URL}/req_code_mapping?select=issue_id&issue_id=eq.{parse.quote(issue_id)}&limit=1",
        )
        return isinstance(rows, list) and len(rows) > 0
    except Exception:
        return False


def _apply_commit_mapping(
    commit_id: str,
    event: dict[str, Any],
    issue_id: str,
    confidence: float,
    source: str,
) -> None:
    commit_payload = {
        "commit_id": commit_id,
        "message": event.get("message"),
        "timestamp": event.get("timestamp"),
        "author": event.get("author"),
        "confidence": round(float(confidence), 4),
        "source": source,
    }
    request_json(
        "POST",
        f"{BASE_REST_URL}/rpc/append_commit_to_requirement",
        payload={"p_issue_id": issue_id, "p_commit_data": commit_payload},
    )
    patch_row(
        "extension_events",
        f"commit_id=eq.{parse.quote(commit_id)}",
        {"issue_id": issue_id},
    )


def fetch_issues() -> list[dict[str, Any]]:
    return get_rows("req_code_mapping", "issue_id,title,description,commits", order="created_at.asc", limit=500)


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
            results.append({"commit_id": commit_row["commit_id"], "issue_id": best_issue_id, "score": best_score})
        else:
            results.append({"commit_id": commit_row["commit_id"], "issue_id": None, "score": best_score})

    return results


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
            patch_row("req_code_mapping", f"issue_id=eq.{parse.quote(issue_id)}", {"commits": matched_commit_ids})

        if matched_commit_ids:
            matched_issue_count += 1
            total_linked_commits += len(matched_commit_ids)

        updates.append({"issue_id": issue_id, "commits": matched_commit_ids, "matches": issue_to_matches[issue_id]})

    return {
        "updated_issues": len(updates),
        "matched_issues": matched_issue_count,
        "linked_commits": total_linked_commits,
        "updates": updates,
    }


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


def count_rows(table: str, select: str, filter_query: str) -> int:
    # Lightweight approximate count for health visibility in MVP.
    response = request_json(
        "GET",
        f"{BASE_REST_URL}/{table}?select={select}&{filter_query}&limit=5000",
    )
    if not isinstance(response, list):
        return 0
    return len(response)


def upsert_row(table: str, payload: dict[str, Any], on_conflict: str) -> Any:
    headers = {
        **DEFAULT_HEADERS,
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=representation",
    }
    conflict = parse.urlencode({"on_conflict": on_conflict})
    return request_json("POST", f"{BASE_REST_URL}/{table}?{conflict}", payload=[payload], headers=headers)


def patch_row(table: str, filters: str, payload: dict[str, Any]) -> Any:
    headers = {
        **DEFAULT_HEADERS,
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    return request_json("PATCH", f"{BASE_REST_URL}/{table}?{filters}", payload=payload, headers=headers)


def delete_rows(table: str, filters: str) -> Any:
    headers = {**DEFAULT_HEADERS, "Prefer": "return=representation"}
    return request_json("DELETE", f"{BASE_REST_URL}/{table}?{filters}", headers=headers)


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
