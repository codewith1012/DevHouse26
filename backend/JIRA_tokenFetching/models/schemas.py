from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

class JiraTicket(BaseModel):
    issue_id: str
    title: str
    description: Optional[str] = None
    status: Optional[str] = None
    issue_type: Optional[str] = None
    priority: Optional[str] = None
    project_key: Optional[str] = None
    assignee_email: Optional[str] = None
    reporter_email: Optional[str] = None
    jira_created_at: Optional[datetime] = None
    jira_updated_at: Optional[datetime] = None
    commits: List[str] = []

class JiraWebhookPayload(BaseModel):
    webhook_event: str = Field(..., alias="webhookEvent")
    issue: Optional[dict] = None
    timestamp: int

class SyncResponse(BaseModel):
    status: str
    synced: int
    errors: int
