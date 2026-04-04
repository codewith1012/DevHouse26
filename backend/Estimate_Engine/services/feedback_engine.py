from datetime import datetime, timezone

from models.schemas import AdaptiveWeights, FeedbackRecord


class FeedbackEngine:
    def derive_weights(self, feedback_summary: dict) -> AdaptiveWeights:
        total_samples = int(feedback_summary.get("total_samples", 0))
        heuristic_error = float(feedback_summary.get("avg_heuristic_error", 0) or 0)
        llm_error = float(feedback_summary.get("avg_llm_error", 0) or 0)

        if total_samples < 3 or heuristic_error <= 0 or llm_error <= 0:
            return AdaptiveWeights(
                heuristic_weight=0.45,
                llm_weight=0.55,
                reason="Using default weights because there is not enough historical feedback yet.",
            )

        heuristic_score = 1 / heuristic_error
        llm_score = 1 / llm_error
        total = heuristic_score + llm_score
        return AdaptiveWeights(
            heuristic_weight=round(heuristic_score / total, 2),
            llm_weight=round(llm_score / total, 2),
            reason="Weights derived from lower historical absolute error receiving more trust.",
        )

    def build_feedback_record(
        self,
        *,
        issue_id: str,
        heuristic_score: float,
        llm_score: float,
        predicted_score: float,
        actual_effort_proxy: float,
        signal_count: int,
        issue_duration_hours: float,
    ) -> FeedbackRecord:
        absolute_error = round(abs(predicted_score - actual_effort_proxy), 2)
        relative_error = round(absolute_error / max(actual_effort_proxy, 1.0), 2)
        return FeedbackRecord(
            issue_id=issue_id,
            heuristic_score=heuristic_score,
            llm_score=llm_score,
            predicted_score=predicted_score,
            actual_effort_proxy=round(actual_effort_proxy, 2),
            absolute_error=absolute_error,
            relative_error=relative_error,
            signal_count=signal_count,
            issue_duration_hours=round(issue_duration_hours, 2),
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def calculate_actual_effort_proxy(
        self,
        *,
        signal_count: int,
        total_lines_changed: int,
        review_comments: int,
        reopen_count: int,
        failed_tests: int,
        issue_duration_hours: float,
        actual_hours: float | None = None,
    ) -> float:
        if actual_hours is not None:
            return actual_hours

        proxy = 0.0
        proxy += signal_count * 0.35
        proxy += total_lines_changed / 160
        proxy += review_comments * 0.2
        proxy += reopen_count * 1.5
        proxy += failed_tests * 0.25
        proxy += min(issue_duration_hours / 24, 4.0)
        return max(1.0, round(proxy, 2))


feedback_engine = FeedbackEngine()
