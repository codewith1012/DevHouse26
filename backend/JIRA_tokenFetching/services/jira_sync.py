import os
import time
from functools import lru_cache
from typing import Any, List, Optional

import requests
from dotenv import load_dotenv
from fastembed import TextEmbedding
from supabase import Client, create_client

load_dotenv()

EMBEDDING_MODEL_NAME = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIMENSION = 384


@lru_cache(maxsize=1)
def get_embed_model() -> TextEmbedding:
    print(f"[INFO] Downloading/loading embedding model {EMBEDDING_MODEL_NAME} ...")
    started = time.perf_counter()
    # Keep thread count low for Render memory stability.
    model = TextEmbedding(model_name=EMBEDDING_MODEL_NAME, threads=1)
    elapsed = round(time.perf_counter() - started, 2)
    print(f"[INFO] Embedding model loaded successfully! (took {elapsed} seconds)")
    return model


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

        # Model is cached globally and reused across requests/instances.
        self.embed_model = get_embed_model()
        self._current_issue_id: str = "unknown"

    def parse_adf_to_text(self, adf: Optional[Any]) -> str:
        """Recursively parses Atlassian Document Format (ADF) to plain text."""
        if not adf:
            return ""

        if isinstance(adf, str):
            return adf

        text_parts = []

        def walk(node):
            if isinstance(node, str):
                text_parts.append(node)
                return
            if not isinstance(node, dict):
                return
            if node.get("type") == "text":
                text_parts.append(node.get("text", ""))
            content = node.get("content")
            if isinstance(content, list):
                for child in content:
                    walk(child)

        walk(adf)
        return " ".join(part for part in text_parts if part)

    @staticmethod
    def _normalize_spaces(text: str) -> str:
        return " ".join(str(text or "").split())

    def _build_embedding_text(
        self,
        title: str,
        description: str,
        issue_type: str,
        priority: str,
    ) -> str:
        passage_text = f"{title} {description} {issue_type} {priority}"
        return self._normalize_spaces(passage_text)

    def generate_req_embedding(self, text: str) -> list[float]:
        """
        Generates a resilient vector(384) embedding payload for Supabase.
        Returns [] on failure so callers can omit req_embedding when needed.
        """
        issue_id = self._current_issue_id or "unknown"
        try:
            cleaned_text = self._normalize_spaces(text)
            # Always prepend passage: for requirement-side asymmetric encoding.
            prefixed_text = f"passage: {cleaned_text}"
            embeddings = list(self.embed_model.embed([prefixed_text]))
            if not embeddings:
                raise ValueError("Embedding model returned no vectors")
            vector = [float(value) for value in embeddings[0].tolist()]
            if len(vector) != EMBEDDING_DIMENSION:
                raise ValueError(
                    f"Embedding dimension mismatch for {issue_id}. "
                    f"Expected {EMBEDDING_DIMENSION}, got {len(vector)}"
                )
            print(f"[EMBEDDING] Generated vector for {issue_id} (length: {len(vector)})")
            return vector
        except Exception as exc:
            print(f"[EMBEDDING] Failed for {issue_id}: {exc}")
            return []

    def get_issue_data(self, issue: dict) -> dict:
        """Extracts and formats relevant fields from a Jira issue JSON and computes its semantic vector."""
        fields = issue.get("fields", {})

        issue_id = issue.get("key") or ""
        # Extract core text fields
        title = fields.get("summary", "") or ""
        description = self.parse_adf_to_text(fields.get("description")) or ""
        issue_type = fields.get("issuetype", {}).get("name") or ""
        priority = fields.get("priority", {}).get("name") or ""

        cleaned_text = self._build_embedding_text(title, description, issue_type, priority)
        self._current_issue_id = issue_id
        vector = self.generate_req_embedding(cleaned_text)

        record = {
            "issue_id": issue_id,
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
        }
        if vector:
            # Must be a JSON list of floats so Supabase stores vector(384) correctly.
            record["req_embedding"] = vector
        return record

    def upsert_to_supabase(self, records: List[dict]):
        """Upserts a list of Jira tickets into the req_code_mapping table."""
        if not records:
            return

        # Supabase upsert preserves commits because this payload omits the commits column.
        try:
            self.supabase.table("req_code_mapping").upsert(
                records,
                on_conflict="issue_id",
            ).execute()
            for record in records:
                issue_id = record.get("issue_id")
                vector = record.get("req_embedding")
                vector_state = len(vector) if isinstance(vector, list) else "NULL"
                print(f"[INFO] Upserted {issue_id} with embedding: {vector_state}")
        except Exception as e:
            print(f"[ERROR] Supabase upsert failed: {e}")
            raise

    def delete_from_supabase(self, issue_id: str):
        """Deletes a Jira ticket from the req_code_mapping table by issue_id."""
        if not issue_id:
            return

        try:
            self.supabase.table("req_code_mapping").delete().eq("issue_id", issue_id).execute()
            print(f"[INFO] Deleted issue {issue_id}")
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

    def _jira_search_page(self, next_page_token: Optional[str], max_results: int) -> dict:
        search_url = f"{self.url}/rest/api/3/search/jql"
        payload = {
            "jql": f"project='{self.project}'",
            "fields": [
                "summary",
                "description",
                "status",
                "issuetype",
                "priority",
                "project",
                "assignee",
                "reporter",
                "created",
                "updated",
            ],
            "maxResults": max_results,
        }
        if next_page_token:
            payload["nextPageToken"] = next_page_token

        response = requests.post(search_url, json=payload, auth=self.auth, timeout=60)
        print(f"[DEBUG] Jira Response Status: {response.status_code}")
        if response.status_code != 200:
            print(f"[ERROR] Jira API failed: {response.text}")
            raise RuntimeError(f"Jira API failed with status {response.status_code}")
        return response.json()

    def sync_all_tickets(self) -> int:
        """Fetches all tickets from the defined Jira project and syncs them to Supabase."""
        synced_count = 0
        next_page_token = None
        max_results = 100
        active_issue_ids: set[str] = set()

        while True:
            data = self._jira_search_page(next_page_token=next_page_token, max_results=max_results)
            issues = data.get("issues", [])
            print(f"[DEBUG] Fetched {len(issues)} issues from Jira")

            if not issues:
                print(f"[DEBUG] No issues found in this page for project {self.project}")
                if not next_page_token and synced_count == 0:
                    self.delete_missing_project_issues(active_issue_ids)
                break

            records = []
            for issue in issues:
                issue_id = issue.get("key")
                try:
                    record = self.get_issue_data(issue)
                    if not record.get("issue_id"):
                        print("[WARN] Skipping issue without key in Jira response")
                        continue
                    records.append(record)
                except Exception as exc:
                    print(f"[ERROR] Failed issue parsing for {issue_id}: {exc}")

            active_issue_ids.update(
                record["issue_id"]
                for record in records
                if record.get("issue_id")
            )

            if records:
                print(f"[DEBUG] Attempting to upsert {len(records)} records to Supabase")
                self.upsert_to_supabase(records)
                synced_count += len(records)

            next_page_token = data.get("nextPageToken")
            if not next_page_token:
                break

        self.delete_missing_project_issues(active_issue_ids)
        print(f"[DEBUG] Sync completed. Total synced: {synced_count}")
        return synced_count

    def backfill_missing_requirement_embeddings(
        self,
        batch_size: int = 100,
        max_batches: int = 20,
    ) -> int:
        """
        Backfills Jira requirement embeddings for rows missing either embedding column.
        Uses existing req_code_mapping fields and stores into both embedding columns.
        """
        print("[JIRA] Startup requirement embedding backfill started...")
        total_processed = 0
        offset = 0
        scanned_batches = 0

        while scanned_batches < max_batches:
            scanned_batches += 1
            try:
                response = (
                    self.supabase.table("req_code_mapping")
                    .select("issue_id,title,description,issue_type,priority,embedding,req_embedding")
                    .range(offset, offset + batch_size - 1)
                    .execute()
                )
            except Exception as exc:
                print(f"[JIRA] Backfill read failed at offset {offset}: {exc}")
                break

            rows = response.data or []
            if not rows:
                break

            for row in rows:
                issue_id = str(row.get("issue_id") or "").strip()
                if not issue_id:
                    continue

                has_embedding = isinstance(row.get("embedding"), list) and len(row["embedding"]) > 0
                has_req_embedding = isinstance(row.get("req_embedding"), list) and len(row["req_embedding"]) > 0
                if has_embedding and has_req_embedding:
                    continue

                text = self._build_embedding_text(
                    str(row.get("title") or ""),
                    str(row.get("description") or ""),
                    str(row.get("issue_type") or ""),
                    str(row.get("priority") or ""),
                )
                self._current_issue_id = issue_id
                vector = self.generate_req_embedding(text)
                if not vector:
                    continue

                try:
                    (
                        self.supabase.table("req_code_mapping")
                        .update({"embedding": vector, "req_embedding": vector})
                        .eq("issue_id", issue_id)
                        .execute()
                    )
                    total_processed += 1
                except Exception as exc:
                    print(f"[JIRA] Backfill write failed for {issue_id}: {exc}")

            offset += batch_size

        print(f"[JIRA] Initial Jira requirements embedding completed. Processed {total_processed} issues.")
        return total_processed


@lru_cache(maxsize=1)
def get_jira_client() -> JiraClient:
    return JiraClient()
