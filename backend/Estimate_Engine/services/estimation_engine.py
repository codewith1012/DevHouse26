from datetime import datetime
from uuid import uuid4

from database.config import settings
from database.repository import estimate_repository
from models.schemas import (
    AdaptiveWeights,
    CommitEstimateResponse,
    CommitSignalRequest,
    DashboardResponse,
    DevelopmentSignalResponse,
    EstimateCreateRequest,
    FeedbackCloseRequest,
    FeedbackRecord,
    FeedbackSummary,
    EstimateHistoryEntry,
    EstimateResponse,
    EstimateTask,
    ExtensionEventRequest,
    IssueEstimateResponse,
    EstimateStatus,
    PollResult,
    PollStatus,
    PullRequestSignalRequest,
    ReworkSignalRequest,
    TestFailureSignalRequest,
)
from services.drift_engine import drift_engine
from services.feedback_engine import feedback_engine
from services.heuristic_engine import heuristic_engine
from services.ollama_client import ollama_client


class EstimationEngine:
    async def create_estimate(self, payload: EstimateCreateRequest) -> EstimateResponse:
        heuristic_result = heuristic_engine.analyze(payload.requirement)
        llm_result = await ollama_client.generate_estimate(
            payload.requirement,
            heuristic_result.detected_features,
        )

        final_hours = round(
            (heuristic_result.estimated_hours * 0.45) + (llm_result.estimated_hours * 0.55),
            1,
        )
        confidence = round(min(0.95, (llm_result.confidence * 0.7) + 0.2), 2)

        record = EstimateResponse(
            id=str(uuid4()),
            requirement=payload.requirement,
            estimated_hours=final_hours,
            confidence=confidence,
            breakdown={
                "heuristic_hours": heuristic_result.estimated_hours,
                "llm_hours": llm_result.estimated_hours,
                "heuristic_features": heuristic_result.detected_features,
                "llm_breakdown": llm_result.breakdown,
                "heuristic_rationale": heuristic_result.rationale,
                "llm_summary": llm_result.summary,
            },
            status=EstimateStatus.CREATED,
        )
        estimate_repository.save(record)
        return record

    async def create_estimate_for_issue(self, issue_id: str) -> IssueEstimateResponse:
        issue = estimate_repository.get_requirement_by_issue_id(issue_id)
        if issue is None:
            raise ValueError("Requirement not found")

        return await self._estimate_issue(issue)

    async def process_commit_signal(self, payload: CommitSignalRequest) -> CommitEstimateResponse:
        issue = estimate_repository.get_requirement_by_issue_id(payload.issue_id)
        if issue is None:
            raise ValueError("Requirement not found")

        signal = estimate_repository.insert_development_signal(
            issue_id=payload.issue_id,
            signal_type="commit",
            source="git",
            payload=payload.model_dump(),
            external_event_id=payload.commit_sha,
        )
        previous_score = self._coerce_float(issue.get("final_score"))
        requirement = self._build_requirement_text(issue)
        impact = drift_engine.analyze_commit_impact(requirement, payload, previous_score)
        estimate = await self._estimate_from_signal(
            issue=issue,
            signal=signal,
            impact=impact,
            signal_type="commit",
            extra_breakdown={"commit_signal": signal.model_dump()},
        )

        return CommitEstimateResponse(
            issue_id=payload.issue_id,
            commit_sha=payload.commit_sha,
            signal=signal,
            impact=impact,
            estimate=estimate,
        )

    async def process_extension_event(self, payload: ExtensionEventRequest) -> CommitEstimateResponse:
        mapped_signal = self._map_extension_event_to_commit_signal(payload)
        external_event_id = self._build_extension_external_id(payload)
        issue = estimate_repository.get_requirement_by_issue_id(mapped_signal.issue_id)
        if issue is None:
            raise ValueError("Requirement not found")
        signal = estimate_repository.insert_development_signal(
            issue_id=mapped_signal.issue_id,
            signal_type="commit",
            source="extension",
            payload=payload.model_dump(),
            external_event_id=external_event_id,
        )
        previous_score = self._coerce_float(issue.get("final_score"))
        requirement = self._build_requirement_text(issue)
        impact = drift_engine.analyze_commit_impact(requirement, mapped_signal, previous_score)
        estimate = await self._estimate_from_signal(
            issue=issue,
            signal=signal,
            impact=impact,
            signal_type="extension_commit",
            extra_breakdown={"extension_event": payload.model_dump()},
        )
        result = CommitEstimateResponse(
            issue_id=mapped_signal.issue_id,
            commit_sha=mapped_signal.commit_sha,
            signal=signal,
            impact=impact,
            estimate=estimate,
        )
        result.estimate.breakdown["extension_event"] = {
            "developer_id": payload.developer_id,
            "repository_name": payload.repository_name,
            "branch": payload.branch,
            "modules_touched": payload.modules_touched,
            "active_minutes": payload.active_minutes,
            "focus_ratio": payload.focus_ratio,
            "attendance_pct": payload.attendance_pct,
        }
        return result

    async def process_pr_signal(self, payload: PullRequestSignalRequest) -> IssueEstimateResponse:
        issue = estimate_repository.get_requirement_by_issue_id(payload.issue_id)
        if issue is None:
            raise ValueError("Requirement not found")
        signal = estimate_repository.insert_development_signal(
            issue_id=payload.issue_id,
            signal_type="pull_request",
            source="git",
            payload=payload.model_dump(),
            external_event_id=f"pr:{payload.issue_id}:{payload.pr_number or payload.title}",
        )
        impact = drift_engine.analyze_pr_impact(
            self._build_requirement_text(issue),
            payload,
            self._coerce_float(issue.get("final_score")),
        )
        return await self._estimate_from_signal(
            issue=issue,
            signal=signal,
            impact=impact,
            signal_type="pull_request",
            extra_breakdown={"pull_request_signal": signal.model_dump()},
        )

    async def process_test_failure_signal(self, payload: TestFailureSignalRequest) -> IssueEstimateResponse:
        issue = estimate_repository.get_requirement_by_issue_id(payload.issue_id)
        if issue is None:
            raise ValueError("Requirement not found")
        signal = estimate_repository.insert_development_signal(
            issue_id=payload.issue_id,
            signal_type="test_failure",
            source="ci",
            payload=payload.model_dump(),
            external_event_id=f"test:{payload.issue_id}:{payload.suite}:{payload.failed_tests}",
        )
        impact = drift_engine.analyze_test_failure_impact(
            self._build_requirement_text(issue),
            payload,
            self._coerce_float(issue.get("final_score")),
        )
        return await self._estimate_from_signal(
            issue=issue,
            signal=signal,
            impact=impact,
            signal_type="test_failure",
            extra_breakdown={"test_failure_signal": signal.model_dump()},
        )

    async def process_rework_signal(self, payload: ReworkSignalRequest) -> IssueEstimateResponse:
        issue = estimate_repository.get_requirement_by_issue_id(payload.issue_id)
        if issue is None:
            raise ValueError("Requirement not found")
        signal = estimate_repository.insert_development_signal(
            issue_id=payload.issue_id,
            signal_type="rework",
            source="workflow",
            payload=payload.model_dump(),
            external_event_id=f"rework:{payload.issue_id}:{payload.reason}",
        )
        impact = drift_engine.analyze_rework_impact(
            self._build_requirement_text(issue),
            payload,
            self._coerce_float(issue.get("final_score")),
        )
        return await self._estimate_from_signal(
            issue=issue,
            signal=signal,
            impact=impact,
            signal_type="rework",
            extra_breakdown={"rework_signal": signal.model_dump()},
        )

    def get_history_for_issue(self, issue_id: str) -> list[EstimateHistoryEntry]:
        return estimate_repository.get_estimate_history(issue_id)

    async def close_feedback_loop(self, payload: FeedbackCloseRequest) -> FeedbackRecord:
        issue = estimate_repository.get_requirement_by_issue_id(payload.issue_id)
        if issue is None:
            raise ValueError("Requirement not found")
        signals = estimate_repository.get_recent_signals(payload.issue_id)
        signal_count = len(signals)
        total_lines_changed = 0
        review_comments = 0
        reopen_count = 0
        failed_tests = 0
        for signal in signals:
            body = signal.get("payload") or {}
            total_lines_changed += int(body.get("lines_added", 0) or 0) + int(body.get("lines_deleted", 0) or 0)
            review_comments += int(body.get("review_comments", 0) or 0)
            failed_tests += int(body.get("failed_tests", 0) or 0)
            if body.get("reopened") or signal.get("signal_type") in {"rework", "pull_request"} and body.get("is_reopened"):
                reopen_count += 1

        issue_duration_hours = self._calculate_issue_duration_hours(issue)
        actual_effort_proxy = feedback_engine.calculate_actual_effort_proxy(
            signal_count=signal_count,
            total_lines_changed=total_lines_changed,
            review_comments=review_comments,
            reopen_count=reopen_count,
            failed_tests=failed_tests,
            issue_duration_hours=issue_duration_hours,
            actual_hours=payload.actual_hours,
        )
        record = feedback_engine.build_feedback_record(
            issue_id=payload.issue_id,
            heuristic_score=self._coerce_float(issue.get("heuristic_score")) or 0.0,
            llm_score=self._coerce_float(issue.get("llm_score")) or 0.0,
            predicted_score=self._coerce_float(issue.get("final_score")) or 0.0,
            actual_effort_proxy=actual_effort_proxy,
            signal_count=signal_count,
            issue_duration_hours=issue_duration_hours,
        )
        return estimate_repository.insert_feedback_record(record)

    def get_feedback_summary(self) -> FeedbackSummary:
        raw_summary = estimate_repository.summarize_feedback()
        adaptive_weights = feedback_engine.derive_weights(raw_summary)
        return FeedbackSummary(
            total_samples=int(raw_summary.get("total_samples", 0)),
            avg_absolute_error=float(raw_summary.get("avg_absolute_error", 0.0)),
            avg_relative_error=float(raw_summary.get("avg_relative_error", 0.0)),
            avg_actual_effort_proxy=float(raw_summary.get("avg_actual_effort_proxy", 0.0)),
            adaptive_weights=adaptive_weights,
        )

    def get_dashboard(self, issue_id: str) -> DashboardResponse:
        issue = estimate_repository.get_requirement_by_issue_id(issue_id)
        current_estimate: IssueEstimateResponse | None = None
        if issue is not None:
            current_estimate = IssueEstimateResponse(
                issue_id=issue_id,
                title=(issue.get("title") or ""),
                requirement=self._build_requirement_text(issue),
                heuristic_score=self._coerce_float(issue.get("heuristic_score")) or 0.0,
                llm_score=self._coerce_float(issue.get("llm_score")) or 0.0,
                final_score=self._coerce_float(issue.get("final_score")) or 0.0,
                confidence=self._coerce_float(issue.get("confidence")) or 0.0,
                uncertainty=str(issue.get("uncertainty") or "unknown"),
                estimate_breakdown=[
                    EstimateTask(**task) for task in (issue.get("estimate_breakdown") or [])
                ],
                breakdown={
                    "last_signal_type": issue.get("last_signal_type"),
                    "last_estimated_at": issue.get("last_estimated_at"),
                    "adaptive_weights": self._get_adaptive_weights().model_dump(),
                },
                status=EstimateStatus.UPDATED,
            )

        feedback_records = estimate_repository.get_feedback_records(issue_id)
        feedback_error = feedback_records[0] if feedback_records else None
        recent_signals = estimate_repository.get_recent_signal_responses(issue_id, limit=10)
        history = estimate_repository.get_estimate_history(issue_id)[:10]
        poll_raw = estimate_repository.get_pending_extension_event_status(limit=20)
        poll_status = PollStatus(
            pending_events=int(poll_raw["pending_events"]),
            pending_event_ids=list(poll_raw["pending_event_ids"]),
            recent_processed_signal_ids=list(poll_raw["recent_processed_signal_ids"]),
            recent_processed_signals=list(poll_raw["recent_processed_signals"]),
        )

        return DashboardResponse(
            issue_id=issue_id,
            current_estimate=current_estimate,
            drift_level=str(issue.get("drift_level") if issue else "unknown"),
            feedback_error=feedback_error,
            feedback_summary=self.get_feedback_summary(),
            recent_signal_timeline=recent_signals,
            estimate_history=history,
            poll_status=poll_status,
        )

    async def poll_extension_events(self) -> PollResult:
        rows = estimate_repository.get_extension_events_batch(settings.extension_poll_batch_size)
        processed = 0
        skipped = 0
        details: list[str] = []
        for row in rows:
            try:
                event = estimate_repository.build_extension_event(row)
                await self.process_extension_event(event)
                processed += 1
                details.append(f"Processed {event.commit_id} for {event.issue_id or event.linked_issue}")
            except Exception as exc:
                skipped += 1
                details.append(f"Skipped event {row.get('commit_id')}: {exc}")
        return PollResult(processed_events=processed, skipped_events=skipped, details=details)

    async def _estimate_from_signal(
        self,
        *,
        issue: dict,
        signal: DevelopmentSignalResponse,
        impact,
        signal_type: str,
        extra_breakdown: dict | None = None,
    ) -> IssueEstimateResponse:
        breakdown = {"signal": signal.model_dump(), "impact": impact.model_dump()}
        if extra_breakdown:
            breakdown.update(extra_breakdown)
        return await self._estimate_issue(
            issue,
            commit_delta=impact.delta_hours,
            change_reason=impact.change_reason,
            drift_level=impact.drift_level,
            signal_type=signal_type,
            signal_id=signal.id,
            extra_breakdown=breakdown,
        )

    async def _estimate_issue(
        self,
        issue: dict,
        *,
        commit_delta: float = 0.0,
        change_reason: str | None = None,
        drift_level: str = "low",
        signal_type: str = "estimate_refresh",
        signal_id: str | None = None,
        extra_breakdown: dict | None = None,
    ) -> IssueEstimateResponse:
        issue_id = issue["issue_id"]
        requirement = self._build_requirement_text(issue)
        heuristic_result = heuristic_engine.analyze(requirement)
        llm_result = await ollama_client.generate_estimate(
            requirement,
            heuristic_result.detected_features,
        )

        heuristic_score = round(heuristic_result.estimated_hours, 1)
        llm_score = round(llm_result.estimated_hours, 1)
        weights = self._get_adaptive_weights()
        base_score = (heuristic_score * weights.heuristic_weight) + (llm_score * weights.llm_weight)
        final_score = round(base_score + commit_delta, 1)
        confidence = self._calculate_confidence(heuristic_score, llm_score, llm_result.confidence)
        uncertainty = self._calculate_uncertainty(requirement, heuristic_result.detected_features)
        estimate_breakdown = self._build_estimate_breakdown(
            heuristic_result.detected_features,
            llm_result.breakdown,
            round(max(base_score, 0.5), 1),
        )
        if commit_delta > 0:
            estimate_breakdown.append(
                EstimateTask(
                    task="Commit-driven scope and rework adjustment",
                    hours=round(commit_delta, 1),
                    source=signal_type,
                )
            )

        updated_issue = estimate_repository.save_issue_scores(
            issue_id=issue_id,
            heuristic_score=heuristic_score,
            llm_score=llm_score,
            final_score=final_score,
            confidence=confidence,
            uncertainty=uncertainty,
            estimate_breakdown=[task.model_dump() for task in estimate_breakdown],
            change_reason=change_reason,
            drift_level=drift_level,
            signal_type=signal_type,
            signal_id=signal_id,
        )

        title = updated_issue.get("title") or issue.get("title") or ""
        requirement_text = self._build_requirement_text(updated_issue)
        breakdown = {
            "heuristic_features": heuristic_result.detected_features,
            "heuristic_rationale": heuristic_result.rationale,
            "llm_breakdown": [task.model_dump() for task in llm_result.breakdown],
            "llm_summary": llm_result.summary,
            "adaptive_weights": weights.model_dump(),
        }
        if extra_breakdown:
            breakdown.update(extra_breakdown)
        return IssueEstimateResponse(
            issue_id=issue_id,
            title=title,
            requirement=requirement_text,
            heuristic_score=heuristic_score,
            llm_score=llm_score,
            final_score=final_score,
            confidence=confidence,
            uncertainty=uncertainty,
            estimate_breakdown=estimate_breakdown,
            breakdown=breakdown,
            status=EstimateStatus.UPDATED,
        )

    def _build_requirement_text(self, issue: dict) -> str:
        title = (issue.get("title") or "").strip()
        description = (issue.get("description") or "").strip()
        if title and description:
            return f"{title}\n\n{description}"
        return title or description

    def _map_extension_event_to_commit_signal(self, payload: ExtensionEventRequest) -> CommitSignalRequest:
        issue_id = (payload.issue_id or payload.linked_issue or "").strip()
        if not issue_id:
            raise ValueError("Extension event does not include issue_id or linked_issue")

        changed_files = [file.file_path for file in payload.files]
        files_added = sum(1 for file in payload.files if file.change_type == "added")
        files_deleted = sum(1 for file in payload.files if file.change_type == "deleted")
        tests_changed = sum(
            1
            for file in payload.files
            if "test" in file.file_path.lower()
            or file.file_path.lower().endswith("_test.py")
            or file.file_path.lower().endswith(".spec.ts")
        )

        return CommitSignalRequest(
            issue_id=issue_id,
            commit_sha=payload.commit_id,
            commit_message=payload.message,
            changed_files=changed_files,
            files_added=files_added,
            files_deleted=files_deleted,
            lines_added=payload.additions,
            lines_deleted=payload.deletions,
            tests_changed=tests_changed,
        )

    def _coerce_float(self, value: object) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _build_extension_external_id(self, payload: ExtensionEventRequest) -> str:
        return f"{payload.developer_id}:{payload.repository_name}:{payload.commit_id}"

    def _get_adaptive_weights(self) -> AdaptiveWeights:
        return feedback_engine.derive_weights(estimate_repository.summarize_feedback())

    def _calculate_issue_duration_hours(self, issue: dict) -> float:
        start = issue.get("jira_created_at") or issue.get("created_at")
        end = issue.get("jira_updated_at") or issue.get("updated_at")
        if not start or not end:
            return 0.0
        try:
            start_dt = self._parse_iso_datetime(str(start))
            end_dt = self._parse_iso_datetime(str(end))
            return max((end_dt - start_dt).total_seconds() / 3600, 0.0)
        except ValueError:
            return 0.0

    def _parse_iso_datetime(self, value: str):
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)

    def _calculate_confidence(self, heuristic_score: float, llm_score: float, llm_confidence: float) -> float:
        delta = abs(heuristic_score - llm_score)
        if delta <= 2:
            confidence = 0.9
        elif delta <= 5:
            confidence = 0.75
        elif delta <= 10:
            confidence = 0.6
        else:
            confidence = 0.4
        return round(min(0.95, (confidence * 0.7) + (llm_confidence * 0.3)), 2)

    def _calculate_uncertainty(self, requirement: str, features: list[str]) -> str:
        text = requirement.lower()
        word_count = len(requirement.split())
        vague_terms = ["some", "maybe", "etc", "thing", "stuff", "basic", "simple", "roughly"]
        vague_hits = sum(1 for term in vague_terms if term in text)

        if word_count < 12 or vague_hits >= 2 or not features:
            return "high"
        if word_count < 25 or vague_hits == 1 or len(features) <= 1:
            return "medium"
        return "low"

    def _build_estimate_breakdown(
        self,
        detected_features: list[str],
        llm_breakdown: list[EstimateTask],
        final_score: float,
    ) -> list[EstimateTask]:
        heuristic_tasks = self._feature_tasks(detected_features)
        tasks = heuristic_tasks + llm_breakdown
        if not tasks:
            tasks = [EstimateTask(task="Core implementation", hours=final_score, source="heuristic")]

        total_hours = sum(task.hours for task in tasks)
        if total_hours <= 0:
            return [EstimateTask(task="Core implementation", hours=final_score, source="heuristic")]

        scale = final_score / total_hours
        return [
            EstimateTask(
                task=task.task,
                hours=round(max(task.hours * scale, 0.5), 1),
                source=task.source,
            )
            for task in tasks
        ]

    def _feature_tasks(self, detected_features: list[str]) -> list[EstimateTask]:
        task_map = {
            "api": EstimateTask(task="API contract and endpoint implementation", hours=3.0, source="heuristic"),
            "authentication": EstimateTask(task="Authentication and access control", hours=4.0, source="heuristic"),
            "dashboard": EstimateTask(task="Dashboard data and interactions", hours=3.5, source="heuristic"),
            "integration": EstimateTask(task="External system integration", hours=4.5, source="heuristic"),
            "database": EstimateTask(task="Database schema and queries", hours=4.0, source="heuristic"),
            "realtime": EstimateTask(task="Realtime updates and event handling", hours=5.0, source="heuristic"),
            "analytics": EstimateTask(task="Analytics calculations and reporting", hours=4.0, source="heuristic"),
            "notification": EstimateTask(task="Notification flow implementation", hours=2.5, source="heuristic"),
            "upload": EstimateTask(task="File upload handling", hours=2.5, source="heuristic"),
            "admin": EstimateTask(task="Admin workflows and permissions", hours=3.0, source="heuristic"),
        }
        return [task_map[feature] for feature in detected_features if feature in task_map]


estimation_engine = EstimationEngine()
