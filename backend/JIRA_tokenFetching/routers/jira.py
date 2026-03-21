from fastapi import APIRouter, Request, HTTPException, Depends
from models.schemas import JiraWebhookPayload, SyncResponse
from services.jira_sync import JiraClient
from datetime import datetime

router = APIRouter(tags=["Jira"])

@router.post("/webhooks/webhook1")
async def handle_jira_webhook(request: Request):
    """
    Receives real-time updates from Jira (Issue Created/Updated/Deleted).
    """
    try:
        payload = await request.json()
        client = JiraClient()

        webhook_event = (payload.get("webhookEvent") or "").lower()
        issue = payload.get("issue")
        if not issue:
            return {"status": "ignored", "reason": "no_issue_in_payload"}

        issue_id = issue.get("key")
        if "delete" in webhook_event:
            client.delete_from_supabase(issue_id)
            return {"status": "success", "action": "deleted", "issue_id": issue_id}

        record = client.get_issue_data(issue)
        client.upsert_to_supabase([record])

        return {"status": "success", "action": "upserted", "issue_id": record["issue_id"]}

    except Exception as e:
        print(f"[ERROR] Webhook processing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/jira/sync", response_model=SyncResponse)
def bulk_sync_jira_tickets(client: JiraClient = Depends()):
    """
    Triggers a manual search for all tickets in the project.
    """
    try:
        synced_count = client.sync_all_tickets()
        return SyncResponse(status="ok", synced=synced_count, errors=0)
    except Exception as e:
        print(f"[ERROR] Bulk sync failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
