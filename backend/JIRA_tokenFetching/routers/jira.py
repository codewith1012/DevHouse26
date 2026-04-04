from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from models.schemas import SyncResponse
from services.jira_sync import JiraClient, get_jira_client

router = APIRouter(tags=["Jira"])


def _extract_issue_id(payload: dict) -> str:
    issue = payload.get("issue") or {}
    if issue.get("key"):
        return str(issue["key"])
    if payload.get("issue_key"):
        return str(payload["issue_key"])
    if payload.get("issueKey"):
        return str(payload["issueKey"])
    return ""


def _process_webhook_upsert(payload: dict) -> None:
    try:
        print("[WEBHOOK] Starting upsert task")
        client = get_jira_client()
        issue = payload.get("issue") or {}
        issue_id = _extract_issue_id(payload)

        if not issue and not issue_id:
            print("[WARN] Jira webhook upsert skipped: no issue payload and no issue_id")
            return

        # Some Jira webhook configs send partial issue objects. Fetch full issue when needed.
        if issue_id and (not issue.get("fields") or not issue.get("key")):
            fetched_issue = client.fetch_issue_by_key(issue_id)
            if fetched_issue:
                issue = fetched_issue

        if issue_id and not issue.get("key"):
            issue["key"] = issue_id

        record = client.get_issue_data(issue)
        if not record.get("issue_id"):
            print("[WARN] Jira webhook upsert skipped: missing issue_id")
            return

        client.upsert_to_supabase([record])
        print(f"[WEBHOOK] Finished upsert task for {record.get('issue_id')}")
    except Exception as exc:
        print(f"[ERROR] Background Jira webhook upsert failed: {exc}")


def _process_webhook_delete(issue_id: str) -> None:
    try:
        if not issue_id:
            print("[WARN] Jira webhook delete skipped: missing issue_id")
            return
        print(f"[WEBHOOK] Starting delete task for {issue_id}")
        client = get_jira_client()
        client.delete_from_supabase(issue_id)
        print(f"[WEBHOOK] Finished delete task for {issue_id}")
    except Exception as exc:
        print(f"[ERROR] Background Jira webhook delete failed for {issue_id}: {exc}")


@router.post("/webhooks/webhook1")
async def handle_jira_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Receives real-time updates from Jira (Issue Created/Updated/Deleted).
    Returns quickly and processes Supabase sync in background.
    """
    try:
        payload = await request.json()
        webhook_event = (payload.get("webhookEvent") or "").lower()
        issue_id = _extract_issue_id(payload)

        if "delete" in webhook_event:
            background_tasks.add_task(_process_webhook_delete, issue_id)
            return {"status": "accepted", "action": "delete_queued", "issue_id": issue_id}

        issue = payload.get("issue")
        if not issue:
            return {"status": "ignored", "reason": "no_issue_in_payload"}

        background_tasks.add_task(_process_webhook_upsert, payload)
        return {"status": "accepted", "action": "upsert_queued", "issue_id": issue_id}

    except Exception as e:
        print(f"[ERROR] Webhook processing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jira/sync", response_model=SyncResponse)
def bulk_sync_jira_tickets(client: JiraClient = Depends(get_jira_client)):
    """
    Triggers a manual search for all tickets in the project.
    """
    try:
        synced_count = client.sync_all_tickets()
        return SyncResponse(status="ok", synced=synced_count, errors=0)
    except Exception as e:
        print(f"[ERROR] Bulk sync failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jira/verify-embeddings")
def verify_embeddings(client: JiraClient = Depends(get_jira_client)):
    """Returns total row count and how many rows still have NULL embedding."""
    try:
        total_response = (
            client.supabase.table("req_code_mapping")
            .select("issue_id", count="exact", head=True)
            .execute()
        )
        null_embedding_response = (
            client.supabase.table("req_code_mapping")
            .select("issue_id", count="exact", head=True)
            .is_("embedding", "null")
            .execute()
        )

        total = int(total_response.count or 0)
        null_embedding = int(null_embedding_response.count or 0)
        return {
            "status": "ok",
            "total_rows": total,
            "null_embedding_rows": null_embedding,
            "non_null_embedding_rows": max(total - null_embedding, 0),
        }
    except Exception as exc:
        print(f"[ERROR] Embedding verification failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
