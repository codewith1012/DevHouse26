from datetime import datetime, timezone

from supabase import Client, create_client

from database.config import settings
from models.schemas import (
    CommitUpdateRequest,
    EstimateResponse,
    EstimateStatus,
    EstimateUpdateResponse,
    IssueEstimateResponse,
)
from services.drift_engine import drift_engine


class EstimateRepository:
    def __init__(self) -> None:
        self._records: dict[str, EstimateResponse] = {}
        self._client: Client | None = None
        if settings.supabase_url and (settings.supabase_service_key or settings.supabase_key):
            self._client = create_client(
                settings.supabase_url,
                settings.supabase_service_key or settings.supabase_key,
            )

    def save(self, record: EstimateResponse) -> None:
        self._records[record.id] = record

    def get(self, estimate_id: str) -> EstimateResponse | None:
        return self._records.get(estimate_id)

    def get_requirement_by_issue_id(self, issue_id: str) -> dict | None:
        if self._client is None:
            raise RuntimeError("Supabase is not configured")

        response = (
            self._client.table(settings.supabase_table)
            .select("*")
            .eq("issue_id", issue_id)
            .limit(1)
            .execute()
        )
        if not response.data:
            return None
        return response.data[0]

    def save_issue_scores(
        self,
        issue_id: str,
        heuristic_score: float,
        llm_score: float,
        final_score: float,
        confidence: float,
        uncertainty: str,
        estimate_breakdown: list[dict],
    ) -> dict:
        if self._client is None:
            raise RuntimeError("Supabase is not configured")

        existing_row = self.get_requirement_by_issue_id(issue_id)
        if existing_row is None:
            raise ValueError(f"No row found for issue_id '{issue_id}'")

        previous_score = self._coerce_optional_float(existing_row.get("final_score"))
        timestamp = datetime.now(timezone.utc).isoformat()
        response = (
            self._client.table(settings.supabase_table)
            .update(
                {
                    "heuristic_score": heuristic_score,
                    "llm_score": llm_score,
                    "final_score": final_score,
                    "confidence": confidence,
                    "uncertainty": uncertainty,
                    "estimate_breakdown": estimate_breakdown,
                    "last_estimated_at": timestamp,
                }
            )
            .eq("issue_id", issue_id)
            .execute()
        )
        if not response.data:
            raise ValueError(f"No row updated for issue_id '{issue_id}'")

        if previous_score is not None and previous_score != final_score:
            self.insert_estimate_history(
                issue_id=issue_id,
                previous_score=previous_score,
                updated_score=final_score,
                change_reason="Estimate recomputed from current requirement using heuristic and Ollama outputs.",
                changed_at=timestamp,
            )

        return response.data[0]

    def insert_estimate_history(
        self,
        issue_id: str,
        previous_score: float,
        updated_score: float,
        change_reason: str,
        changed_at: str,
    ) -> None:
        if self._client is None:
            raise RuntimeError("Supabase is not configured")

        self._client.table("estimate_history").insert(
            {
                "issue_id": issue_id,
                "previous_score": previous_score,
                "updated_score": updated_score,
                "change_reason": change_reason,
                "changed_at": changed_at,
            }
        ).execute()

    def _coerce_optional_float(self, value: object) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def update_from_commit(self, payload: CommitUpdateRequest) -> EstimateUpdateResponse | None:
        record = self.get(payload.estimate_id)
        if record is None:
            return None

        adjustment = min(len(payload.changed_files) * 1.5, 8.0)
        updated_hours = round(record.estimated_hours + adjustment, 1)
        record.estimated_hours = updated_hours
        record.status = EstimateStatus.UPDATED
        self.save(record)

        return EstimateUpdateResponse(
            id=record.id,
            status=EstimateStatus.UPDATED,
            updated_estimated_hours=updated_hours,
            change_summary=drift_engine.summarize_commit_impact(payload),
        )


estimate_repository = EstimateRepository()
