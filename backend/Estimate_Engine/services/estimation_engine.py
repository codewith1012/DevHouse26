from uuid import uuid4

from database.repository import estimate_repository
from models.schemas import (
    EstimateCreateRequest,
    EstimateResponse,
    EstimateTask,
    IssueEstimateResponse,
    EstimateStatus,
)
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

        requirement = self._build_requirement_text(issue)
        heuristic_result = heuristic_engine.analyze(requirement)
        llm_result = await ollama_client.generate_estimate(
            requirement,
            heuristic_result.detected_features,
        )

        heuristic_score = round(heuristic_result.estimated_hours, 1)
        llm_score = round(llm_result.estimated_hours, 1)
        final_score = round((heuristic_score * 0.45) + (llm_score * 0.55), 1)
        confidence = self._calculate_confidence(heuristic_score, llm_score, llm_result.confidence)
        uncertainty = self._calculate_uncertainty(requirement, heuristic_result.detected_features)
        estimate_breakdown = self._build_estimate_breakdown(
            heuristic_result.detected_features,
            llm_result.breakdown,
            final_score,
        )

        updated_issue = estimate_repository.save_issue_scores(
            issue_id=issue_id,
            heuristic_score=heuristic_score,
            llm_score=llm_score,
            final_score=final_score,
            confidence=confidence,
            uncertainty=uncertainty,
            estimate_breakdown=[task.model_dump() for task in estimate_breakdown],
        )

        title = updated_issue.get("title") or issue.get("title") or ""
        requirement_text = self._build_requirement_text(updated_issue)
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
            breakdown={
                "heuristic_features": heuristic_result.detected_features,
                "heuristic_rationale": heuristic_result.rationale,
                "llm_breakdown": [task.model_dump() for task in llm_result.breakdown],
                "llm_summary": llm_result.summary,
            },
            status=EstimateStatus.UPDATED,
        )

    def _build_requirement_text(self, issue: dict) -> str:
        title = (issue.get("title") or "").strip()
        description = (issue.get("description") or "").strip()
        if title and description:
            return f"{title}\n\n{description}"
        return title or description

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
