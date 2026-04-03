import json

import httpx

from database.config import settings
from models.schemas import EstimateTask, LLMEstimate


class OllamaClient:
    async def generate_estimate(self, requirement: str, features: list[str]) -> LLMEstimate:
        if not settings.ollama_enabled:
            return self._fallback_response(requirement, features)

        prompt = self._build_prompt(requirement, features)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{settings.ollama_base_url}/api/generate",
                    json={
                        "model": settings.ollama_model,
                        "prompt": prompt,
                        "stream": False,
                        "format": "json",
                    },
                )
                response.raise_for_status()
                data = response.json()
        except Exception:
            return self._fallback_response(requirement, features)

        raw_output = data.get("response", "{}")
        try:
            parsed = json.loads(raw_output)
        except json.JSONDecodeError:
            return self._fallback_response(requirement, features)

        return LLMEstimate(
            estimated_hours=float(parsed.get("estimated_hours", 8)),
            confidence=float(parsed.get("confidence", 0.55)),
            breakdown=self._normalize_breakdown(parsed.get("breakdown")),
            summary=parsed.get("summary", "LLM-generated estimate"),
        )

    def _build_prompt(self, requirement: str, features: list[str]) -> str:
        feature_text = ", ".join(features) if features else "none detected"
        return (
            "You are a software estimation assistant. "
            "Return compact JSON with keys estimated_hours, confidence, breakdown, summary. "
            "The breakdown must be an array of objects with task and hours. "
            f"Requirement: {requirement}\n"
            f"Detected features: {feature_text}"
        )

    def _fallback_response(self, requirement: str, features: list[str]) -> LLMEstimate:
        feature_count = max(len(features), 1)
        return LLMEstimate(
            estimated_hours=float(6 + feature_count * 3),
            confidence=0.5,
            breakdown=[
                EstimateTask(task="Requirement review and clarifications", hours=2.0, source="llm"),
                EstimateTask(task="Implementation tasks inferred from requirement text", hours=3.0 + feature_count, source="llm"),
                EstimateTask(task="Testing and validation buffer", hours=1.0 + (feature_count * 0.5), source="llm"),
            ],
            summary=f"Fallback estimate used for requirement of {len(requirement.split())} words.",
        )

    def _normalize_breakdown(self, breakdown: object) -> list[EstimateTask]:
        if not isinstance(breakdown, list) or not breakdown:
            return [EstimateTask(task="Initial implementation estimate from Ollama", hours=8.0, source="llm")]

        normalized: list[EstimateTask] = []
        for item in breakdown:
            if isinstance(item, dict):
                task = str(item.get("task", "LLM task")).strip() or "LLM task"
                try:
                    hours = float(item.get("hours", 0))
                except (TypeError, ValueError):
                    hours = 0.0
                normalized.append(EstimateTask(task=task, hours=max(hours, 0.5), source="llm"))
            elif isinstance(item, str):
                normalized.append(EstimateTask(task=item.strip() or "LLM task", hours=2.0, source="llm"))

        return normalized or [EstimateTask(task="Initial implementation estimate from Ollama", hours=8.0, source="llm")]


ollama_client = OllamaClient()
