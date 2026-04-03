import math
from typing import Any, List, Dict


def cosine_similarity(left: List[float], right: List[float]) -> float:
    """Traditional cosine similarity, pulled from original main.py for completeness."""
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return numerator / (left_norm * right_norm)


def normalize_spaces(text: str) -> str:
    return " ".join(str(text or "").split())


def extract_patch_summary(patch: str, max_hunks: int = 4) -> str:
    """
    Truncates a git diff/patch to keep only the first `max_hunks` hunks.
    This prevents massive patches from blowing up the token window for embeddings.
    """
    if not patch:
        return ""

    # Split by the unified diff hunk header "@@"
    parts = patch.split("@@")

    # parts[0] is usually file header info.
    # parts[1] is the first hunk header, parts[2] is the hunk content, etc.
    # We want the header + (max_hunks) hunks.
    # The split creates 2 items per hunk after the first file header.
    max_parts = 1 + (max_hunks * 2)

    summary = "@@".join(parts[:max_parts])
    if len(parts) > max_parts:
        summary += "\n... (patch truncated)"

    return summary


def build_commit_context(commit_data: Dict[str, Any]) -> str:
    """
    Builds a rich context string for the commit, combining message,
    file paths, and a truncated patch summary.

    EMBEDDING PREFIX STRATEGY (BAAI/bge-small-en-v1.5 asymmetric encoding):
      - Commits use 'query: ' prefix  → added at embed time in main.py
      - Requirements use 'passage: ' prefix  → added at embed time in main.py
    This function returns raw text WITHOUT any prefix for clean separation of concerns.
    """
    message = str(commit_data.get("message") or "").strip()
    if not message:
        message = "No commit message"

    # Extract file paths safely from "files" or nested "files_json"
    files = []
    direct_files = commit_data.get("files")
    if isinstance(direct_files, list):
        files = direct_files
    else:
        files_json = commit_data.get("files_json")
        if isinstance(files_json, dict) and "files" in files_json:
            files = files_json["files"]
        elif isinstance(files_json, list):
            files = files_json

    file_paths = [str(f.get("file_path", "")) for f in files if isinstance(f, dict) and f.get("file_path")]

    diff_patch = str(commit_data.get("diff_patch") or "")
    patch_summary = extract_patch_summary(diff_patch, max_hunks=4)

    # Build parts using pipe-delimited format for clarity
    parts = [message]  # NO prefix here — caller applies 'query: ' at embed time

    if file_paths:
        parts.append(f"Changed files: {', '.join(file_paths[:8])}")  # cap at 8 files

    if patch_summary:
        parts.append(f"Code changes: {patch_summary}")

    return normalize_spaces(" | ".join(parts))


def should_skip_commit(message: str) -> bool:
    """
    Returns True if a commit message is too trivial to be worth embedding.
    Uses substring matching so 'fix typo' or 'update readme' are caught too.
    """
    msg = message.lower().strip()
    if len(msg) < 8:
        return True
    skip_keywords = {
        "merge", "initial commit", "init", "wip", "update readme",
        "bump version", "test", "fix typo", "dummy", "temp", "todo",
    }
    return any(kw in msg for kw in skip_keywords)


def calculate_heuristic_boost(commit: Dict[str, Any], requirement: Dict[str, Any]) -> float:
    """
    Calculates a heuristic score boost if the commit explicitly mentions the Jira ID.
    This corrects for situations where vector search fails to match exact IDs.
    """
    boost = 0.0
    issue_id = str(requirement.get("issue_id", "")).lower()
    message = str(commit.get("message", "")).lower()

    # 1. Jira ID direct match in commit message (HUGE boost)
    if issue_id and issue_id in message:
        boost += 0.35

    # More domain-specific heuristic rules can be added here easily
    return boost


def re_rank_candidates(candidates: List[Dict[str, Any]], commit: Dict[str, Any], commit_embedding: List[float] = None) -> Dict[str, Any]:
    """
    Re-ranks a list of candidate requirements returned by the Supabase pgvector RPC.
    Uses adaptive weighted scoring:
      - When a Jira ID match is detected: 65% semantic + 35% heuristic (heuristic is trustworthy)
      - Otherwise: 75% semantic + 25% heuristic (semantics dominate)
    """
    if not candidates:
        return None

    best = None
    highest_score = -1.0

    for req in candidates:
        semantic_score = float(req.get("similarity", 0.0))
        heuristic_boost = calculate_heuristic_boost(commit, req)

        # Adaptive weights: trust heuristic more when Jira ID is explicitly mentioned
        semantic_weight = 0.65 if heuristic_boost > 0 else 0.75
        final_score = (semantic_score * semantic_weight) + (heuristic_boost * (1 - semantic_weight))

        req["confidence"] = round(final_score, 4)
        req["semantic_score"] = round(semantic_score, 4)
        req["boost"] = round(heuristic_boost, 4)

        if final_score > highest_score:
            highest_score = final_score
            best = req

    return best
