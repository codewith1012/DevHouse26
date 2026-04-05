import json
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any


WORD_RE = re.compile(r"[a-z0-9_+#.-]+", re.IGNORECASE)


def clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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


def tokenize(*parts: Any) -> set[str]:
    tokens: set[str] = set()
    for part in parts:
        text = str(part or "").lower()
        for token in WORD_RE.findall(text):
            normalized = token.strip("._-")
            if len(normalized) >= 3:
                tokens.add(normalized)
    return tokens


def parse_tech_stack(value: Any) -> list[str]:
    if isinstance(value, list):
        items = value
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
            items = parsed if isinstance(parsed, list) else [raw]
        except json.JSONDecodeError:
            items = [item.strip() for item in raw.split(",") if item.strip()]
    else:
        return []

    result: list[str] = []
    for item in items:
        if isinstance(item, dict):
            label = str(item.get("name") or item.get("label") or "").strip()
            if label:
                result.append(label)
        else:
            label = str(item).strip()
            if label:
                result.append(label)
    return result


def normalize_developer_identity(developer: dict[str, Any]) -> set[str]:
    return {
        str(developer.get("developer_id") or "").strip().lower(),
        str(developer.get("email") or "").strip().lower(),
        str(developer.get("name") or "").strip().lower(),
    } - {""}


def events_for_developer(developer: dict[str, Any], events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    identities = normalize_developer_identity(developer)
    if not identities:
        return []

    matched: list[dict[str, Any]] = []
    for event in events:
        candidates = {
            str(event.get("developer_id") or "").strip().lower(),
            str(event.get("author_email") or "").strip().lower(),
            str(event.get("author") or "").strip().lower(),
        } - {""}
        if identities & candidates:
            matched.append(event)
    return matched


def build_requirement_profile(issue: dict[str, Any], issue_events: list[dict[str, Any]]) -> dict[str, Any]:
    title = str(issue.get("title") or "").strip()
    description = str(issue.get("description") or "").strip()
    issue_type = str(issue.get("issue_type") or "").strip().lower()
    priority = str(issue.get("priority") or "").strip().lower()
    tokens = tokenize(title, description, issue_type, priority)

    touched_repos = {
        str(event.get("repository_name") or "").strip().lower()
        for event in issue_events
        if str(event.get("repository_name") or "").strip()
    }
    total_commits = len(issue_events)
    total_changes = sum(max(safe_float(event.get("total_changes")), 0.0) for event in issue_events)

    complexity = clamp(
        (total_commits / 10.0) * 0.35
        + (total_changes / 1600.0) * 0.35
        + (0.2 if priority in {"high", "highest", "critical", "blocker"} else 0.08)
        + (0.1 if issue_type in {"feature", "epic", "story"} else 0.04)
    )
    ideal_experience = 1.0 + (complexity * 7.0)

    return {
        "tokens": tokens,
        "touched_repos": touched_repos,
        "complexity": round(complexity, 4),
        "ideal_experience": round(ideal_experience, 2),
        "total_commits": total_commits,
        "total_changes": round(total_changes, 2),
    }


def compute_skill_match(requirement_profile: dict[str, Any], developer: dict[str, Any]) -> tuple[float, list[str]]:
    tech_stack = parse_tech_stack(developer.get("tech_stack"))
    tech_tokens = tokenize(" ".join(tech_stack), developer.get("summary"), developer.get("role"), developer.get("seniority_level"))
    requirement_tokens = requirement_profile["tokens"]
    overlap = sorted(requirement_tokens & tech_tokens)

    score = 0.0
    if requirement_tokens:
        score = len(overlap) / max(min(len(requirement_tokens), 8), 1)
    if tech_stack and not overlap:
        score = min(0.18 + (len(tech_stack) / 20.0), 0.32)

    reasons: list[str] = []
    if overlap:
        reasons.append(f"Strong stack overlap on {', '.join(overlap[:3])}.")
    elif tech_stack:
        reasons.append(f"Profile includes {', '.join(tech_stack[:3])}, giving partial skill coverage.")
    return clamp(score), reasons


def compute_familiarity_match(requirement_profile: dict[str, Any], developer_events: list[dict[str, Any]], issue_id: str) -> tuple[float, list[str]]:
    if not developer_events:
        return 0.0, []

    issue_matches = sum(1 for event in developer_events if str(event.get("issue_id") or "").strip().upper() == issue_id.upper())
    touched_repos = requirement_profile["touched_repos"]
    same_repo_events = sum(
        1
        for event in developer_events
        if str(event.get("repository_name") or "").strip().lower() in touched_repos
    )

    familiarity = clamp((issue_matches / 3.0) * 0.55 + (same_repo_events / 8.0) * 0.45)
    reasons: list[str] = []
    if issue_matches:
        reasons.append(f"Already contributed {issue_matches} linked commits to this requirement.")
    if same_repo_events:
        reasons.append(f"Has {same_repo_events} commits in the same repository context.")
    return familiarity, reasons


def compute_experience_fit(requirement_profile: dict[str, Any], developer: dict[str, Any]) -> tuple[float, list[str]]:
    years = safe_float(developer.get("experience_years"), 0.0)
    ideal = requirement_profile["ideal_experience"]
    if ideal <= 0:
        return 0.5, []

    ratio = years / ideal
    score = 1 - min(abs(1 - ratio), 1)
    if ratio > 1:
        score = min(1.0, 0.72 + min(ratio - 1, 1.0) * 0.18)
    score = clamp(score)

    reason = f"Experience profile is {years:.1f} years against an estimated need of {ideal:.1f} years."
    return score, [reason]


def compute_availability_score(developer: dict[str, Any], developer_events: list[dict[str, Any]], now: datetime) -> tuple[float, list[str]]:
    capacity = max(int(safe_float(developer.get("current_capacity"), 3)), 1)
    cutoff = now.timestamp() - (14 * 86400)
    active_issues = {
        str(event.get("issue_id") or "").strip().upper()
        for event in developer_events
        if str(event.get("issue_id") or "").strip()
        and (parse_datetime(event.get("timestamp")) or now).timestamp() >= cutoff
    }
    load_ratio = len(active_issues) / capacity
    score = clamp(1 - min(load_ratio, 1.0))
    reason = f"Recent load is {len(active_issues)} active requirements against capacity {capacity}."
    return score, [reason]


def build_developer_recommendations(
    issue: dict[str, Any],
    developers: list[dict[str, Any]],
    issue_events: list[dict[str, Any]],
    all_events: list[dict[str, Any]],
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    issue_id = str(issue.get("issue_id") or "").strip()
    requirement_profile = build_requirement_profile(issue, issue_events)
    recommendations: list[dict[str, Any]] = []

    for developer in developers:
        developer_id = str(developer.get("developer_id") or "").strip()
        if not developer_id or not bool(developer.get("active", True)):
            continue

        developer_history = events_for_developer(developer, all_events)
        skill_match, skill_reasons = compute_skill_match(requirement_profile, developer)
        familiarity_match, familiarity_reasons = compute_familiarity_match(requirement_profile, developer_history, issue_id)
        experience_fit, experience_reasons = compute_experience_fit(requirement_profile, developer)
        availability_score, availability_reasons = compute_availability_score(developer, developer_history, now)

        score = clamp(
            (0.45 * skill_match)
            + (0.30 * familiarity_match)
            + (0.15 * experience_fit)
            + (0.10 * availability_score)
        )

        contributor_map = {
            "skill": 0.45 * skill_match,
            "familiarity": 0.30 * familiarity_match,
            "experience": 0.15 * experience_fit,
            "availability": 0.10 * availability_score,
        }
        ordered_reasons: list[str] = []
        for signal, _ in sorted(contributor_map.items(), key=lambda item: item[1], reverse=True):
            if signal == "skill":
                ordered_reasons.extend(skill_reasons)
            elif signal == "familiarity":
                ordered_reasons.extend(familiarity_reasons)
            elif signal == "experience":
                ordered_reasons.extend(experience_reasons)
            else:
                ordered_reasons.extend(availability_reasons)

        normalized_stack = parse_tech_stack(developer.get("tech_stack"))
        recommendations.append(
            {
                "requirement_id": issue_id,
                "developer_id": developer_id,
                "developer_name": developer.get("name"),
                "developer_email": developer.get("email"),
                "role": developer.get("role"),
                "experience_years": round(safe_float(developer.get("experience_years"), 0.0), 1),
                "tech_stack": normalized_stack,
                "score": round(score, 4),
                "skill_match": round(skill_match, 4),
                "familiarity_match": round(familiarity_match, 4),
                "experience_fit": round(experience_fit, 4),
                "availability_score": round(availability_score, 4),
                "reasons": ordered_reasons[:3],
                "breakdown": {
                    "skill_match": round(skill_match, 4),
                    "familiarity_match": round(familiarity_match, 4),
                    "experience_fit": round(experience_fit, 4),
                    "availability_score": round(availability_score, 4),
                    "requirement_complexity": requirement_profile["complexity"],
                    "ideal_experience": requirement_profile["ideal_experience"],
                    "requirement_commit_count": requirement_profile["total_commits"],
                    "requirement_change_volume": requirement_profile["total_changes"],
                },
            }
        )

    recommendations.sort(key=lambda item: item["score"], reverse=True)
    for index, recommendation in enumerate(recommendations, start=1):
        recommendation["rank"] = index
    return recommendations
