import json
import math
from collections import Counter
from datetime import datetime, timezone
from typing import Any


def clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        if len(raw) == 10:
            return datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
        normalized = raw.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def days_between(start: datetime | None, end: datetime | None) -> float:
    if not start or not end:
        return 0.0
    return max((end - start).total_seconds() / 86400, 0.0)


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def estimate_level(hours: float) -> str:
    if hours < 8:
        return "S"
    if hours < 20:
        return "M"
    if hours < 40:
        return "L"
    return "XL"


def summarize_commit_metrics(events: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    timestamps = [parse_datetime(event.get("timestamp")) for event in events]
    valid_timestamps = [ts for ts in timestamps if ts is not None]
    recent_cutoff = now.timestamp() - (3 * 86400)

    commits_last_3_days = sum(1 for ts in valid_timestamps if ts.timestamp() >= recent_cutoff)
    total_commits = len(events)
    total_changes = sum(max(safe_float(event.get("total_changes")), 0.0) for event in events)
    additions = sum(max(safe_float(event.get("additions")), 0.0) for event in events)
    deletions = sum(max(safe_float(event.get("deletions")), 0.0) for event in events)
    latest_commit = max(valid_timestamps, default=None)
    first_commit = min(valid_timestamps, default=None)

    contributors = Counter(
        str(event.get("author_email") or event.get("author") or "").strip().lower()
        for event in events
        if event.get("author_email") or event.get("author")
    )
    repositories = {
        str(event.get("repository_name") or "").strip()
        for event in events
        if str(event.get("repository_name") or "").strip()
    }
    branches = {
        str(event.get("branch") or "").strip()
        for event in events
        if str(event.get("branch") or "").strip()
    }

    days_since_last_commit = days_between(latest_commit, now) if latest_commit else 0.0
    active_span_days = max(days_between(first_commit, latest_commit), 0.0) if first_commit and latest_commit else 0.0
    churn_ratio = deletions / max(additions + deletions, 1.0)

    return {
        "total_commits": total_commits,
        "commits_last_3_days": commits_last_3_days,
        "total_changes": round(total_changes, 2),
        "additions": round(additions, 2),
        "deletions": round(deletions, 2),
        "contributors": len(contributors),
        "repositories": len(repositories),
        "branches": len(branches),
        "latest_commit_at": latest_commit.isoformat() if latest_commit else None,
        "first_commit_at": first_commit.isoformat() if first_commit else None,
        "days_since_last_commit": round(days_since_last_commit, 2),
        "active_span_days": round(active_span_days, 2),
        "churn_ratio": round(churn_ratio, 4),
    }


def build_heuristic_estimate(issue: dict[str, Any], commit_metrics: dict[str, Any], now: datetime) -> dict[str, Any]:
    issue_type = str(issue.get("issue_type") or "").strip().lower()
    priority = str(issue.get("priority") or "").strip().lower()
    title = str(issue.get("title") or "").strip()
    description = str(issue.get("description") or "").strip()

    start_date = parse_datetime(issue.get("jira_created_at"))
    due_date = parse_datetime(issue.get("due_date"))
    elapsed_days = max(days_between(start_date, now), 0.0)
    days_remaining = days_between(now, due_date) if due_date else 0.0
    total_window_days = days_between(start_date, due_date) if start_date and due_date else 0.0
    schedule_pressure = clamp((elapsed_days / max(total_window_days, 1.0)) if total_window_days else 0.25)

    type_base_hours = {
        "bug": 6.0,
        "task": 10.0,
        "story": 14.0,
        "feature": 22.0,
        "epic": 48.0,
    }.get(issue_type, 12.0)

    priority_multiplier = {
        "lowest": 0.9,
        "low": 0.95,
        "medium": 1.0,
        "high": 1.15,
        "highest": 1.3,
        "critical": 1.35,
        "blocker": 1.4,
    }.get(priority, 1.0)

    text_words = len(f"{title} {description}".split())
    text_complexity = clamp(text_words / 140)
    implementation_keywords = (
        "integration",
        "pipeline",
        "auth",
        "security",
        "migration",
        "dashboard",
        "vector",
        "risk",
        "engine",
        "sync",
        "webhook",
    )
    keyword_hits = sum(
        1
        for keyword in implementation_keywords
        if keyword in f"{title} {description}".lower()
    )
    semantic_complexity = clamp((keyword_hits / 6) + (text_complexity * 0.4))

    commit_complexity = clamp(
        (commit_metrics["total_commits"] / 10.0) * 0.35
        + (commit_metrics["total_changes"] / 1500.0) * 0.35
        + (commit_metrics["contributors"] / 4.0) * 0.15
        + (commit_metrics["repositories"] / 3.0) * 0.15
    )
    churn_penalty = clamp(commit_metrics["churn_ratio"] / 0.45)

    base_hours = type_base_hours * priority_multiplier
    initial_estimate_hours = base_hours * (1 + (text_complexity * 0.45) + (semantic_complexity * 0.35))

    execution_discovery = 1 + (commit_complexity * 0.45) + (churn_penalty * 0.2)
    schedule_adjustment = 1 + max(schedule_pressure - 0.55, 0.0) * 0.25
    heuristic_estimate_hours = initial_estimate_hours * execution_discovery * schedule_adjustment

    observed_progress_hours = min(
        heuristic_estimate_hours * 0.85,
        (commit_metrics["total_commits"] * 1.8) + (commit_metrics["total_changes"] / 140.0),
    )
    remaining_estimate_hours = max(heuristic_estimate_hours - observed_progress_hours, 1.0)
    confidence = clamp(
        0.45
        + min(commit_metrics["total_commits"], 8) * 0.04
        + min(text_words, 120) / 1200.0
    )

    return {
        "initial_estimate_hours": round(initial_estimate_hours, 2),
        "heuristic_estimate_hours": round(heuristic_estimate_hours, 2),
        "remaining_estimate_hours": round(remaining_estimate_hours, 2),
        "completed_effort_hours": round(observed_progress_hours, 2),
        "confidence": round(confidence, 4),
        "breakdown": {
            "type_base_hours": round(type_base_hours, 2),
            "priority_multiplier": round(priority_multiplier, 4),
            "text_complexity": round(text_complexity, 4),
            "semantic_complexity": round(semantic_complexity, 4),
            "commit_complexity": round(commit_complexity, 4),
            "churn_penalty": round(churn_penalty, 4),
            "schedule_pressure": round(schedule_pressure, 4),
        },
    }


def build_llm_prompt(issue: dict[str, Any], commit_metrics: dict[str, Any], heuristic: dict[str, Any]) -> str:
    payload = {
        "requirement_id": issue.get("issue_id"),
        "title": issue.get("title"),
        "description": issue.get("description"),
        "issue_type": issue.get("issue_type"),
        "priority": issue.get("priority"),
        "status": issue.get("status"),
        "jira_created_at": issue.get("jira_created_at"),
        "due_date": issue.get("due_date"),
        "commit_metrics": commit_metrics,
        "heuristic": heuristic,
    }
    return (
        "You are estimating engineering effort for a software requirement. "
        "Return JSON only with keys: estimate_hours, confidence, rationale, task_breakdown. "
        "estimate_hours must be a number, confidence must be 0 to 1, rationale must be an array of short strings, "
        "task_breakdown must be an array of objects with task and hours. "
        "Use the heuristic estimate as a reference, but adjust it if the execution signals suggest more or less work.\n\n"
        f"{json.dumps(payload, ensure_ascii=True)}"
    )


def combine_estimates(
    heuristic: dict[str, Any],
    llm_estimate: dict[str, Any] | None,
    previous_estimate_hours: float | None,
) -> dict[str, Any]:
    heuristic_hours = safe_float(heuristic.get("heuristic_estimate_hours"), 0.0)
    heuristic_remaining = safe_float(heuristic.get("remaining_estimate_hours"), 0.0)
    heuristic_confidence = safe_float(heuristic.get("confidence"), 0.0)

    llm_hours = None
    llm_confidence = None
    rationale: list[str] = []
    task_breakdown: list[dict[str, Any]] = []
    llm_used = False

    if llm_estimate:
        candidate_hours = safe_float(llm_estimate.get("estimate_hours"), 0.0)
        if candidate_hours > 0:
            llm_hours = candidate_hours
            llm_confidence = clamp(safe_float(llm_estimate.get("confidence"), heuristic_confidence))
            llm_used = True
            raw_rationale = llm_estimate.get("rationale") or []
            if isinstance(raw_rationale, list):
                rationale = [str(item).strip() for item in raw_rationale if str(item).strip()]
            raw_tasks = llm_estimate.get("task_breakdown") or []
            if isinstance(raw_tasks, list):
                for item in raw_tasks:
                    if isinstance(item, dict) and str(item.get("task") or "").strip():
                        task_breakdown.append(
                            {
                                "task": str(item.get("task")).strip(),
                                "hours": round(safe_float(item.get("hours"), 0.0), 2),
                            }
                        )

    if llm_hours is not None:
        final_hours = (heuristic_hours * 0.55) + (llm_hours * 0.45)
        confidence = clamp((heuristic_confidence * 0.55) + ((llm_confidence or heuristic_confidence) * 0.45))
    else:
        final_hours = heuristic_hours
        confidence = heuristic_confidence

    remaining_ratio = heuristic_remaining / max(heuristic_hours, 1.0)
    remaining_hours = max(final_hours * remaining_ratio, 1.0)

    drift_hours = 0.0
    drift_direction = "stable"
    if previous_estimate_hours is not None:
        drift_hours = round(final_hours - previous_estimate_hours, 2)
        if drift_hours > 0.5:
            drift_direction = "increased"
        elif drift_hours < -0.5:
            drift_direction = "decreased"

    if not rationale:
        rationale = [
            "Base estimate is derived from requirement type, priority, text complexity, and observed commit activity.",
            "Commit-linked execution signals can raise the estimate when churn or code spread increases.",
        ]
        if drift_direction == "decreased":
            rationale.append("Recent execution signals indicate the team is burning down work faster than earlier assumptions.")
        elif drift_direction == "increased":
            rationale.append("Recent execution signals suggest more implementation effort than the earlier estimate assumed.")

    return {
        "heuristic_estimate_hours": round(heuristic_hours, 2),
        "llm_estimate_hours": round(llm_hours, 2) if llm_hours is not None else None,
        "final_estimate_hours": round(final_hours, 2),
        "remaining_estimate_hours": round(remaining_hours, 2),
        "completed_effort_hours": round(max(final_hours - remaining_hours, 0.0), 2),
        "confidence": round(confidence, 4),
        "estimate_level": estimate_level(final_hours),
        "drift_hours": round(drift_hours, 2),
        "drift_direction": drift_direction,
        "rationale": rationale[:4],
        "task_breakdown": task_breakdown[:6],
        "llm_used": llm_used,
    }

