from models.schemas import (
    CommitImpactResult,
    CommitSignalRequest,
    CommitUpdateRequest,
    PullRequestSignalRequest,
    ReworkSignalRequest,
    TestFailureSignalRequest,
)


class DriftEngine:
    def summarize_commit_impact(self, payload: CommitUpdateRequest) -> str:
        files_changed = len(payload.changed_files)
        message = payload.commit_message.strip() or "No commit message provided"
        return (
            f"Commit impact review: {files_changed} changed files. "
            f"Latest commit message: {message}"
        )

    def analyze_commit_impact(
        self,
        requirement: str,
        signal: CommitSignalRequest,
        previous_score: float | None,
    ) -> CommitImpactResult:
        changed_files = signal.changed_files
        file_count = len(changed_files)
        churn = signal.lines_added + signal.lines_deleted
        text = f"{requirement.lower()} {signal.commit_message.lower()}"

        impact_score = 0.0
        affected_areas: list[str] = []
        risk_factors: list[str] = []

        if file_count:
            impact_score += min(file_count * 0.25, 2.0)
        if churn:
            impact_score += min(churn / 150, 3.0)

        area_rules = {
            "database": ["/migrations/", "migration", ".sql", "models/", "schema"],
            "authentication": ["auth", "login", "token", "permission"],
            "api": ["routes/", "router", "endpoint", "controller", "api"],
            "tests": ["test", "spec", "pytest"],
            "frontend": ["component", ".tsx", ".jsx", ".css", "ui/"],
            "config": [".env", "docker", "yaml", "config"],
        }

        haystack = " ".join(changed_files).lower() + " " + signal.commit_message.lower()
        for area, tokens in area_rules.items():
            if any(token in haystack for token in tokens):
                affected_areas.append(area)

        if "database" in affected_areas:
            impact_score += 1.5
            risk_factors.append("Database or schema changes usually increase integration effort.")
        if "authentication" in affected_areas:
            impact_score += 1.5
            risk_factors.append("Authentication changes can ripple through multiple flows.")
        if "api" in affected_areas:
            impact_score += 1.0
        if signal.tests_changed > 0 or "tests" in affected_areas:
            impact_score += 0.5
            risk_factors.append("Tests changed, which suggests validation or rework effort.")
        if signal.files_added > 0:
            impact_score += min(signal.files_added * 0.3, 1.5)
        if signal.files_deleted > 0:
            impact_score += min(signal.files_deleted * 0.15, 0.8)
        if len(set(affected_areas)) >= 3:
            impact_score += 1.0
            risk_factors.append("Multiple subsystems changed in a single commit.")

        if "fix" in text or "bug" in text or "rework" in text:
            impact_score += 0.8
            risk_factors.append("Bugfix or rework wording suggests underestimation or instability.")

        delta_hours = round(max(0.0, impact_score), 1)
        if delta_hours <= 1.5:
            drift_level = "low"
        elif delta_hours <= 4.0:
            drift_level = "medium"
        else:
            drift_level = "high"

        baseline_text = (
            f"Previous score {previous_score} adjusted by commit activity."
            if previous_score is not None
            else "Initial commit-aware adjustment from current requirement baseline."
        )
        reason_parts = [
            baseline_text,
            f"{file_count} files changed with churn of {churn} lines.",
        ]
        if affected_areas:
            reason_parts.append(f"Affected areas: {', '.join(sorted(set(affected_areas)))}.")
        if risk_factors:
            reason_parts.append(risk_factors[0])

        return CommitImpactResult(
            impact_score=round(impact_score, 2),
            delta_hours=delta_hours,
            drift_level=drift_level,
            change_reason=" ".join(reason_parts),
            affected_areas=sorted(set(affected_areas)),
            risk_factors=risk_factors,
        )

    def analyze_pr_impact(
        self,
        requirement: str,
        signal: PullRequestSignalRequest,
        previous_score: float | None,
    ) -> CommitImpactResult:
        file_count = len(signal.changed_files)
        churn = signal.lines_added + signal.lines_deleted
        impact_score = min(churn / 180, 2.5) + min(file_count * 0.2, 1.5)
        risk_factors: list[str] = []
        affected_areas = self._infer_areas_from_files(signal.changed_files, signal.title)

        if signal.review_comments > 0:
            impact_score += min(signal.review_comments * 0.1, 1.5)
            risk_factors.append("Review comments suggest extra clarification or rework.")
        if signal.review_rounds > 1:
            impact_score += min((signal.review_rounds - 1) * 0.6, 1.8)
            risk_factors.append("Multiple review rounds indicate the implementation needed revision.")
        if signal.is_reopened:
            impact_score += 1.5
            risk_factors.append("Reopened PR indicates scope drift or quality issues.")
        if "breaking-change" in [label.lower() for label in signal.labels]:
            impact_score += 1.2
            risk_factors.append("Breaking change label suggests expanded downstream impact.")

        return self._finalize_impact(
            impact_score=impact_score,
            previous_score=previous_score,
            affected_areas=affected_areas,
            risk_factors=risk_factors,
            change_summary=f"PR signal for '{signal.title}' with {signal.review_comments} review comments.",
            requirement=requirement,
        )

    def analyze_test_failure_impact(
        self,
        requirement: str,
        signal: TestFailureSignalRequest,
        previous_score: float | None,
    ) -> CommitImpactResult:
        impact_score = min(signal.failed_tests * 0.35, 3.0)
        affected_areas = self._infer_areas_from_files(signal.failing_files, " ".join(signal.error_types))
        risk_factors = [f"{signal.failed_tests} failing tests in suite {signal.suite}."]
        severity_weights = {"low": 0.4, "medium": 0.8, "high": 1.5, "critical": 2.5}
        impact_score += severity_weights.get(signal.severity.lower(), 0.8)
        if any("integration" in err.lower() or "timeout" in err.lower() for err in signal.error_types):
            impact_score += 1.2
            risk_factors.append("Integration-style test failures often imply hidden complexity.")
        return self._finalize_impact(
            impact_score=impact_score,
            previous_score=previous_score,
            affected_areas=affected_areas,
            risk_factors=risk_factors,
            change_summary=f"Test-failure signal from suite {signal.suite}.",
            requirement=requirement,
        )

    def analyze_rework_impact(
        self,
        requirement: str,
        signal: ReworkSignalRequest,
        previous_score: float | None,
    ) -> CommitImpactResult:
        impact_score = 1.5 if signal.reopened else 0.8
        impact_score += min(signal.review_comments * 0.12, 1.5)
        impact_score += min(len(signal.changed_files) * 0.15, 1.2)
        affected_areas = self._infer_areas_from_files(signal.changed_files, signal.reason)
        risk_factors = [signal.reason]
        if signal.reopened:
            risk_factors.append("Reopened work is a strong underestimation signal.")
        return self._finalize_impact(
            impact_score=impact_score,
            previous_score=previous_score,
            affected_areas=affected_areas,
            risk_factors=risk_factors,
            change_summary="Rework/reopen signal processed.",
            requirement=requirement,
        )

    def _finalize_impact(
        self,
        *,
        impact_score: float,
        previous_score: float | None,
        affected_areas: list[str],
        risk_factors: list[str],
        change_summary: str,
        requirement: str,
    ) -> CommitImpactResult:
        requirement_features = self._infer_requirement_intent(requirement)
        unexpected_areas = sorted(set(affected_areas) - set(requirement_features))
        if unexpected_areas:
            impact_score += min(len(unexpected_areas) * 0.8, 2.4)
            risk_factors.append(f"Unexpected implementation areas touched: {', '.join(unexpected_areas)}.")

        delta_hours = round(max(0.0, impact_score), 1)
        if delta_hours <= 1.5:
            drift_level = "low"
        elif delta_hours <= 4.0:
            drift_level = "medium"
        else:
            drift_level = "high"

        baseline = (
            f"Previous score {previous_score} adjusted."
            if previous_score is not None
            else "Initial adjustment from current requirement baseline."
        )
        return CommitImpactResult(
            impact_score=round(impact_score, 2),
            delta_hours=delta_hours,
            drift_level=drift_level,
            change_reason=f"{baseline} {change_summary}",
            affected_areas=sorted(set(affected_areas)),
            risk_factors=risk_factors,
        )

    def _infer_areas_from_files(self, changed_files: list[str], extra_text: str) -> list[str]:
        area_rules = {
            "database": ["/migrations/", "migration", ".sql", "models/", "schema"],
            "authentication": ["auth", "login", "token", "permission"],
            "api": ["routes/", "router", "endpoint", "controller", "api"],
            "tests": ["test", "spec", "pytest"],
            "frontend": ["component", ".tsx", ".jsx", ".css", "ui/"],
            "config": [".env", "docker", "yaml", "config"],
        }
        haystack = " ".join(changed_files).lower() + " " + extra_text.lower()
        return [area for area, tokens in area_rules.items() if any(token in haystack for token in tokens)]

    def _infer_requirement_intent(self, requirement: str) -> list[str]:
        text = requirement.lower()
        mapping = {
            "api": ["api", "endpoint", "service"],
            "database": ["database", "table", "sql", "store", "persist"],
            "authentication": ["auth", "login", "permission", "token"],
            "frontend": ["ui", "frontend", "screen", "page", "component"],
            "tests": ["test", "validation", "verify"],
        }
        return [area for area, words in mapping.items() if any(word in text for word in words)]


drift_engine = DriftEngine()
