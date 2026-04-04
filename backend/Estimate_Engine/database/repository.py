from datetime import datetime, timezone

from supabase import Client, create_client

from database.config import settings
from models.schemas import (
    CommitSignalRequest,
    CommitUpdateRequest,
    DevelopmentSignalResponse,
    ExtensionEventRequest,
    FeedbackRecord,
    EstimateHistoryEntry,
    EstimateResponse,
    EstimateStatus,
    EstimateUpdateResponse,
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

    def list_requirements(self, limit: int = 100) -> list[dict]:
        if self._client is None:
            raise RuntimeError("Supabase is not configured")
        response = (
            self._client.table(settings.supabase_table)
            .select("*")
            .limit(limit)
            .execute()
        )
        return response.data or []

    def save_issue_scores(
        self,
        issue_id: str,
        heuristic_score: float,
        llm_score: float,
        final_score: float,
        confidence: float,
        uncertainty: str,
        estimate_breakdown: list[dict],
        change_reason: str | None = None,
        drift_level: str = "low",
        signal_type: str = "estimate_refresh",
        signal_id: str | None = None,
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
                    "drift_level": drift_level,
                    "last_signal_type": signal_type,
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
                change_reason=change_reason or "Estimate recomputed from current requirement using heuristic and Ollama outputs.",
                drift_level=drift_level,
                signal_type=signal_type,
                signal_id=signal_id,
                changed_at=timestamp,
            )

        return response.data[0]

    def insert_estimate_history(
        self,
        issue_id: str,
        previous_score: float,
        updated_score: float,
        change_reason: str,
        drift_level: str,
        signal_type: str,
        signal_id: str | None,
        changed_at: str,
    ) -> None:
        if self._client is None:
            raise RuntimeError("Supabase is not configured")

        delta_score = round(updated_score - previous_score, 1)
        self._client.table("estimate_history").insert(
            {
                "issue_id": issue_id,
                "previous_score": previous_score,
                "updated_score": updated_score,
                "delta_score": delta_score,
                "change_reason": change_reason,
                "drift_level": drift_level,
                "signal_type": signal_type,
                "signal_id": signal_id,
                "changed_at": changed_at,
            }
        ).execute()

    def insert_development_signal(
        self,
        *,
        issue_id: str,
        signal_type: str,
        source: str,
        payload: dict,
        external_event_id: str | None = None,
    ) -> DevelopmentSignalResponse:
        if self._client is None:
            raise RuntimeError("Supabase is not configured")

        if external_event_id:
            existing = (
                self._client.table("development_signals")
                .select("*")
                .eq("external_event_id", external_event_id)
                .limit(1)
                .execute()
            )
            if existing.data:
                row = existing.data[0]
                return DevelopmentSignalResponse(
                    id=str(row.get("id")),
                    issue_id=row["issue_id"],
                    signal_type=row["signal_type"],
                    source=row["source"],
                    payload=row["payload"],
                    created_at=row["created_at"],
                )

        response = (
            self._client.table("development_signals")
            .insert(
                {
                    "issue_id": issue_id,
                    "signal_type": signal_type,
                    "source": source,
                    "payload": payload,
                    "external_event_id": external_event_id,
                }
            )
            .execute()
        )
        if not response.data:
            raise ValueError(f"Signal could not be stored for issue_id '{issue_id}'")

        row = response.data[0]
        return DevelopmentSignalResponse(
            id=str(row.get("id")),
            issue_id=row["issue_id"],
            signal_type=row["signal_type"],
            source=row["source"],
            payload=row["payload"],
            created_at=row["created_at"],
        )

    def signal_exists_for_external_event(self, external_event_id: str) -> bool:
        if self._client is None:
            raise RuntimeError("Supabase is not configured")
        response = (
            self._client.table("development_signals")
            .select("id")
            .eq("external_event_id", external_event_id)
            .limit(1)
            .execute()
        )
        return bool(response.data)

    def get_estimate_history(self, issue_id: str) -> list[EstimateHistoryEntry]:
        if self._client is None:
            raise RuntimeError("Supabase is not configured")

        response = (
            self._client.table("estimate_history")
            .select("*")
            .eq("issue_id", issue_id)
            .order("changed_at", desc=True)
            .execute()
        )
        history: list[EstimateHistoryEntry] = []
        for row in response.data or []:
            history.append(
                EstimateHistoryEntry(
                    id=str(row.get("id")) if row.get("id") is not None else None,
                    issue_id=row["issue_id"],
                    previous_score=float(row["previous_score"]),
                    updated_score=float(row["updated_score"]),
                    delta_score=float(row.get("delta_score") or (float(row["updated_score"]) - float(row["previous_score"]))),
                    change_reason=row["change_reason"],
                    drift_level=row.get("drift_level") or "low",
                    signal_type=row.get("signal_type") or "estimate_refresh",
                    signal_id=str(row.get("signal_id")) if row.get("signal_id") is not None else None,
                    changed_at=row["changed_at"],
                )
            )
        return history

    def get_recent_signals(self, issue_id: str) -> list[dict]:
        if self._client is None:
            raise RuntimeError("Supabase is not configured")
        response = (
            self._client.table("development_signals")
            .select("*")
            .eq("issue_id", issue_id)
            .order("created_at", desc=True)
            .limit(200)
            .execute()
        )
        return response.data or []

    def get_recent_signal_responses(self, issue_id: str, limit: int = 20) -> list[DevelopmentSignalResponse]:
        rows = self.get_recent_signals(issue_id)[:limit]
        return [
            DevelopmentSignalResponse(
                id=str(row.get("id")),
                issue_id=row["issue_id"],
                signal_type=row["signal_type"],
                source=row["source"],
                payload=row["payload"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def get_feedback_records(self, issue_id: str | None = None) -> list[FeedbackRecord]:
        if self._client is None:
            raise RuntimeError("Supabase is not configured")
        query = self._client.table("estimate_feedback").select("*").order("created_at", desc=True)
        if issue_id:
            query = query.eq("issue_id", issue_id)
        response = query.execute()
        records: list[FeedbackRecord] = []
        for row in response.data or []:
            records.append(
                FeedbackRecord(
                    id=str(row.get("id")) if row.get("id") is not None else None,
                    issue_id=row["issue_id"],
                    heuristic_score=float(row["heuristic_score"]),
                    llm_score=float(row["llm_score"]),
                    predicted_score=float(row["predicted_score"]),
                    actual_effort_proxy=float(row["actual_effort_proxy"]),
                    absolute_error=float(row["absolute_error"]),
                    relative_error=float(row["relative_error"]),
                    signal_count=int(row.get("signal_count") or 0),
                    issue_duration_hours=float(row.get("issue_duration_hours") or 0),
                    created_at=row["created_at"],
                )
            )
        return records

    def insert_feedback_record(self, record: FeedbackRecord) -> FeedbackRecord:
        if self._client is None:
            raise RuntimeError("Supabase is not configured")
        response = self._client.table("estimate_feedback").insert(record.model_dump(exclude={"id"})).execute()
        row = response.data[0]
        return FeedbackRecord(
            id=str(row.get("id")) if row.get("id") is not None else None,
            issue_id=row["issue_id"],
            heuristic_score=float(row["heuristic_score"]),
            llm_score=float(row["llm_score"]),
            predicted_score=float(row["predicted_score"]),
            actual_effort_proxy=float(row["actual_effort_proxy"]),
            absolute_error=float(row["absolute_error"]),
            relative_error=float(row["relative_error"]),
            signal_count=int(row.get("signal_count") or 0),
            issue_duration_hours=float(row.get("issue_duration_hours") or 0),
            created_at=row["created_at"],
        )

    def summarize_feedback(self) -> dict:
        records = self.get_feedback_records()
        if not records:
            return {
                "total_samples": 0,
                "avg_absolute_error": 0.0,
                "avg_relative_error": 0.0,
                "avg_actual_effort_proxy": 0.0,
            }

        total = len(records)
        return {
            "total_samples": total,
            "avg_absolute_error": round(sum(r.absolute_error for r in records) / total, 2),
            "avg_relative_error": round(sum(r.relative_error for r in records) / total, 2),
            "avg_actual_effort_proxy": round(sum(r.actual_effort_proxy for r in records) / total, 2),
            "avg_heuristic_error": round(sum(abs(r.actual_effort_proxy - r.heuristic_score) for r in records) / total, 2),
            "avg_llm_error": round(sum(abs(r.actual_effort_proxy - r.llm_score) for r in records) / total, 2),
        }

    def get_extension_events_batch(self, limit: int) -> list[dict]:
        if self._client is None:
            raise RuntimeError("Supabase is not configured")
        response = (
            self._client.table(settings.extension_events_table)
            .select("*")
            .order("timestamp")
            .limit(limit)
            .execute()
        )
        rows = response.data or []
        pending: list[dict] = []
        for row in rows:
            commit_id = row.get("commit_id")
            developer_id = row.get("developer_id")
            repository_name = row.get("repository_name")
            external_event_id = self._build_external_event_id(commit_id, developer_id, repository_name)
            if external_event_id and not self.signal_exists_for_external_event(external_event_id):
                pending.append(row)
        return pending

    def get_pending_extension_event_status(self, limit: int = 20) -> dict:
        pending_rows = self.get_extension_events_batch(limit)
        pending_ids = [
            self._build_external_event_id(
                row.get("commit_id"),
                row.get("developer_id"),
                row.get("repository_name"),
            )
            for row in pending_rows
        ]
        pending_ids = [event_id for event_id in pending_ids if event_id]

        response = (
            self._client.table("development_signals")
            .select("*")
            .eq("source", "extension")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        recent_rows = response.data or []
        recent_signals = [
            DevelopmentSignalResponse(
                id=str(row.get("id")),
                issue_id=row["issue_id"],
                signal_type=row["signal_type"],
                source=row["source"],
                payload=row["payload"],
                created_at=row["created_at"],
            )
            for row in recent_rows
        ]
        recent_ids = [str((row.get("payload") or {}).get("commit_id") or row.get("external_event_id") or row.get("id")) for row in recent_rows]
        return {
            "pending_events": len(pending_ids),
            "pending_event_ids": pending_ids,
            "recent_processed_signal_ids": recent_ids,
            "recent_processed_signals": recent_signals,
        }

    def build_extension_event(self, row: dict) -> ExtensionEventRequest:
        return ExtensionEventRequest(**row)

    def _build_external_event_id(self, commit_id: object, developer_id: object, repository_name: object) -> str | None:
        if not commit_id:
            return None
        return f"{developer_id or 'unknown'}:{repository_name or 'unknown'}:{commit_id}"

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
