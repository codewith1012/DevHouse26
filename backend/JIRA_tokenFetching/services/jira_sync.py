import os
import requests
from typing import List, Optional
from datetime import datetime
from supabase import create_client, Client
from dotenv import load_dotenv
from fastembed import TextEmbedding

load_dotenv()

class JiraClient:
    def __init__(self):
        self.url = os.getenv("JIRA_URL", "").rstrip("/")
        self.email = os.getenv("JIRA_EMAIL", "")
        self.token = os.getenv("JIRA_TOKEN", "")
        self.project = os.getenv("JIRA_PROJECT", "")
        self.auth = (self.email, self.token)
        
        # Supabase setup
        sb_url = os.getenv("SUPABASE_URL", "")
        sb_key = os.getenv("SUPABASE_SERVICE_KEY", "")
        self.supabase: Client = create_client(sb_url, sb_key)
        
        # Initialize the embedding model specifically for Jira tracking
        print("[INFO] Loading BAAI/bge-small-en-v1.5 model...")
        self.embed_model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")

    def parse_adf_to_text(self, adf: Optional[dict]) -> str:
        """Recursively parses Atlassian Document Format (ADF) to plain text."""
        if not adf:
            return ""
        
        text_parts = []
        
        def walk(node):
            if node.get("type") == "text":
                text_parts.append(node.get("text", ""))
            elif "content" in node:
                for child in node["content"]:
                    walk(child)
        
        walk(adf)
        return "".join(text_parts)

    def get_issue_data(self, issue: dict) -> dict:
        """Extracts and formats relevant fields from a Jira issue JSON and computes its semantic vector."""
        fields = issue.get("fields", {})
        
        # Extract core text fields
        title = fields.get("summary", "") or ""
        description = self.parse_adf_to_text(fields.get("description")) or ""
        issue_type = fields.get("issuetype", {}).get("name") or ""
        priority = fields.get("priority", {}).get("name") or ""
        
        # Build the exact contextual paragraph expected by BAAI/bge-small-en-v1.5
        passage_text = f"passage: {title} {description} {issue_type} {priority}"
        cleaned_text = " ".join(passage_text.split())
        
        # Generate embedding vector
        embeddings = list(self.embed_model.embed([cleaned_text]))
        vector = [float(v) for v in embeddings[0].tolist()]

        return {
            "issue_id": issue.get("key"),
            "title": title,
            "description": description,
            "status": fields.get("status", {}).get("name"),
            "issue_type": issue_type,
            "priority": priority,
            "project_key": fields.get("project", {}).get("key"),
            "assignee_email": fields.get("assignee", {}).get("emailAddress") if fields.get("assignee") else None,
            "reporter_email": fields.get("reporter", {}).get("emailAddress") if fields.get("reporter") else None,
            "jira_created_at": fields.get("created"),
            "jira_updated_at": fields.get("updated"),
            "req_embedding": vector
        }

    def upsert_to_supabase(self, records: List[dict]):
        """Upserts a list of Jira tickets into the req_code_mapping table."""
        if not records:
            return
        
        # Supabase upsert will preserve the 'commits' array because it's not in the request body
        try:
            self.supabase.table("req_code_mapping").upsert(
                records, 
                on_conflict="issue_id"
            ).execute()
        except Exception as e:
            print(f"[ERROR] Supabase upsert failed: {e}")

    def delete_from_supabase(self, issue_id: str):
        """Deletes a Jira ticket from the req_code_mapping table by issue_id."""
        if not issue_id:
            return

        try:
            self.supabase.table("req_code_mapping").delete().eq("issue_id", issue_id).execute()
        except Exception as e:
            print(f"[ERROR] Supabase delete failed for {issue_id}: {e}")

    def delete_missing_project_issues(self, active_issue_ids: set[str]):
        """Removes stale issues for the configured Jira project that no longer exist in Jira."""
        if not self.project:
            return

        try:
            response = (
                self.supabase.table("req_code_mapping")
                .select("issue_id")
                .eq("project_key", self.project)
                .execute()
            )
            existing_issue_ids = {
                row["issue_id"]
                for row in (response.data or [])
                if row.get("issue_id")
            }
            stale_issue_ids = existing_issue_ids - active_issue_ids

            for issue_id in stale_issue_ids:
                print(f"[DEBUG] Removing stale issue from Supabase: {issue_id}")
                self.delete_from_supabase(issue_id)
        except Exception as e:
            print(f"[ERROR] Failed to reconcile deleted Jira issues for project {self.project}: {e}")

    def sync_all_tickets(self) -> int:
        """Fetches all tickets from the defined Jira project and syncs them to Supabase."""
        synced_count = 0
        next_page_token = None
        max_results = 100
        active_issue_ids: set[str] = set()
        
        search_url = f"{self.url}/rest/api/3/search/jql"
        print(f"[DEBUG] Hitting Jira URL: {search_url}")
        
        while True:
            payload = {
                "jql": f"project='{self.project}'",
                "fields": ["summary", "description", "status", "issuetype", "priority", "project", "assignee", "reporter", "created", "updated"],
                "maxResults": max_results
            }
            
            if next_page_token:
                payload["nextPageToken"] = next_page_token
            
            response = requests.post(search_url, json=payload, auth=self.auth)
            print(f"[DEBUG] Jira Response Status: {response.status_code}")
            if response.status_code != 200:
                print(f"[ERROR] Jira API failed: {response.text}")
                break
            
            data = response.json()
            issues = data.get("issues", [])
            print(f"[DEBUG] Fetched {len(issues)} issues from Jira")
            if not issues:
                print(f"[DEBUG] No issues found in this page for project {self.project}")
                if not next_page_token and synced_count == 0:
                    self.delete_missing_project_issues(active_issue_ids)
                break
            
            records = [self.get_issue_data(issue) for issue in issues]
            active_issue_ids.update(
                record["issue_id"]
                for record in records
                if record.get("issue_id")
            )
            print(f"[DEBUG] Attempting to upsert {len(records)} records to Supabase")
            self.upsert_to_supabase(records)
            
            synced_count += len(issues)
            next_page_token = data.get("nextPageToken")
            
            if not next_page_token:
                break

        self.delete_missing_project_issues(active_issue_ids)
        print(f"[DEBUG] Sync completed. Total synced: {synced_count}")
        return synced_count
