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
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def days_between(start: datetime | None, end: datetime | None) -> float:
    if not start or not end:
        return 0.0
    return max((end - start).total_seconds() / 86400, 0.0)


def build_requirement_risk(issue: dict[str, Any], events: list[dict[str, Any]], now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    start_date = parse_datetime(issue.get("jira_created_at"))
    deadline = parse_datetime(issue.get("due_date"))
    current_date = now

    event_times = [
        parse_datetime(event.get("timestamp"))
        for event in events
    ]
    recent_cutoff = now.timestamp() - (3 * 86400)
    commits_last_3_days = sum(
        1 for ts in event_times
        if ts is not None and ts.timestamp() >= recent_cutoff
    )
    total_commits = len(events)
    total_changes = sum(max(float(event.get("total_changes") or 0), 0.0) for event in events)

    elapsed_days = max(days_between(start_date, current_date), 1.0)
    remaining_days = max(days_between(current_date, deadline), 0.0) if deadline else 0.0
    total_window_days = max(days_between(start_date, deadline), elapsed_days) if start_date and deadline else elapsed_days

    avg_commits_expected = max(math.ceil(total_window_days / 2), 3)
    velocity = commits_last_3_days / avg_commits_expected if avg_commits_expected else 0.0
    velocity_score = clamp(velocity)
    activity_drop = clamp(1 - velocity_score)

    if start_date and deadline and deadline > start_date:
        time_progress = clamp(days_between(start_date, current_date) / max(days_between(start_date, deadline), 1.0))
    else:
        time_progress = clamp(elapsed_days / max(elapsed_days + 3, 1.0))

    work_progress = velocity_score
    schedule_gap = clamp(time_progress - work_progress)

    latest_commit_time = max((ts for ts in event_times if ts is not None), default=None)
    days_since_last_commit = days_between(latest_commit_time, current_date) if latest_commit_time else elapsed_days
    staleness_score = clamp(days_since_last_commit / 3)

    assignee_email = str(issue.get("assignee_email") or "").strip().lower()
    active_tasks = 1
    ideal_capacity = 3
    load_index = active_tasks / ideal_capacity
    load_score = clamp(load_index / 2)

    author_counts = Counter(str(event.get("author_email") or event.get("author") or "").strip().lower() for event in events if event.get("author_email") or event.get("author"))
    primary_author, primary_author_commits = ("", 0)
    if author_counts:
        primary_author, primary_author_commits = author_counts.most_common(1)[0]
    familiarity_score = clamp(primary_author_commits / max(total_commits, 1)) if total_commits else 0.0
    if assignee_email and assignee_email == primary_author:
        familiarity_score = clamp(familiarity_score + 0.15)
    familiarity_risk = clamp(1 - familiarity_score)

    unique_modules = {
        str(event.get("repository_name") or "").strip()
        for event in events
        if str(event.get("repository_name") or "").strip()
    }
    files_changed = max(total_commits * 2, len(unique_modules))
    dependency_count = len(unique_modules)
    complexity_score = clamp(((files_changed / 20) * 0.5) + ((dependency_count / 10) * 0.5))

    pr_delay_score = 0.0
    review_score = 0.0

    risk_score = clamp(
        (0.20 * activity_drop) +
        (0.20 * schedule_gap) +
        (0.15 * pr_delay_score) +
        (0.10 * review_score) +
        (0.15 * load_score) +
        (0.10 * familiarity_risk) +
        (0.10 * complexity_score) +
        (0.10 * staleness_score)
    )

    risk_level = "LOW" if risk_score < 0.4 else "MEDIUM" if risk_score < 0.7 else "HIGH"

    contributors = {
        "activity_drop": 0.20 * activity_drop,
        "schedule_gap": 0.20 * schedule_gap,
        "pr_delay": 0.15 * pr_delay_score,
        "review_friction": 0.10 * review_score,
        "developer_load": 0.15 * load_score,
        "familiarity_risk": 0.10 * familiarity_risk,
        "complexity": 0.10 * complexity_score,
        "staleness": 0.10 * staleness_score,
    }

    reason_map = {
        "activity_drop": f"Low development activity detected ({commits_last_3_days} commits in the last 3 days)",
        "schedule_gap": "Work progress is trailing behind the time elapsed for this requirement",
        "pr_delay": "PR merge delays are increasing delivery risk",
        "review_friction": "Review friction is slowing down requirement throughput",
        "developer_load": f"Developer load is elevated ({active_tasks} active tasks vs ideal capacity {ideal_capacity})",
        "familiarity_risk": "Requirement ownership familiarity is limited, increasing execution risk",
        "complexity": f"Implementation scope is broad ({files_changed} estimated file touches across {dependency_count} modules)",
        "staleness": f"Recent delivery signals are stale ({max(int(round(days_since_last_commit)), 0)} days since the last commit)",
    }

    top_reasons = [
        reason_map[key]
        for key, _ in sorted(contributors.items(), key=lambda item: item[1], reverse=True)
        if contributors[key] > 0
    ][:3]

    recommendations: list[str] = []
    if velocity_score < 0.5:
        recommendations.append("Check for blockers or split the task into smaller units.")
    if load_score > 0.7:
        recommendations.append("Reassign or rebalance work to a lower-load developer.")
    if familiarity_risk > 0.7:
        recommendations.append("Pair this requirement with someone who has stronger module familiarity.")
    if complexity_score > 0.7:
        recommendations.append("Break the requirement into smaller subtasks with clearer ownership.")
    if staleness_score > 0.7:
        recommendations.append("Schedule an immediate progress review because recent development activity has gone quiet.")
    if schedule_gap > 0.5:
        recommendations.append("Reduce scope or pull forward delivery support before the due date slips.")
    if not recommendations:
        recommendations.append("Keep the current execution plan steady and continue linking commits to requirement progress.")

    return {
        "requirement_id": issue.get("issue_id"),
        "title": issue.get("title"),
        "time": {
            "start_date": issue.get("jira_created_at"),
            "deadline": issue.get("due_date"),
            "current_date": current_date.isoformat(),
            "days_remaining": round(remaining_days, 2),
        },
        "inputs": {
            "commits_last_3_days": commits_last_3_days,
            "avg_commits_expected": avg_commits_expected,
            "lines_changed": int(round(total_changes)),
            "days_since_last_commit": round(days_since_last_commit, 2),
            "active_tasks": active_tasks,
            "ideal_capacity": ideal_capacity,
            "familiarity_score": round(familiarity_score, 4),
            "files_changed": files_changed,
            "dependency_count": dependency_count,
        },
        "risk_score": round(risk_score, 4),
        "risk_level": risk_level,
        "breakdown": {
            "velocity_score": round(velocity_score, 4),
            "activity_drop": round(activity_drop, 4),
            "schedule_gap": round(schedule_gap, 4),
            "pr_delay": round(pr_delay_score, 4),
            "review_friction": round(review_score, 4),
            "developer_load": round(load_score, 4),
            "familiarity_risk": round(familiarity_risk, 4),
            "complexity": round(complexity_score, 4),
            "staleness": round(staleness_score, 4),
        },
        "reasons": top_reasons,
        "recommendations": recommendations[:4],
    }
