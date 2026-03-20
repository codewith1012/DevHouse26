import json
import os
import re
from pathlib import Path
from typing import Any, Optional, Union
from urllib import error, parse, request
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity as sklearn_cosine_similarity

ROOT_DIR = Path(__file__).resolve().parent
load_dotenv()

STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "create",
    "file",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "python",
    "screen",
    "task",
    "that",
    "the",
    "this",
    "to",
    "using",
    "where",
    "with",
}

COMMON_CODE_WORDS = {
    "added",
    "branch",
    "change",
    "commit",
    "diff",
    "false",
    "index",
    "json",
    "line",
    "master",
    "mode",
    "modified",
    "new",
    "null",
    "true",
}

SORT_TERMS = {"sort", "sorted", "sorting", "bubble", "merge", "quick", "insertion", "selection", "heap"}
MIN_SCORE = 5.8
MAX_MATCHES_PER_ISSUE = 8


# Environment Variables are now loaded via load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL") or os.getenv("VITE_SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY") or os.getenv("VITE_SUPABASE_ANON_KEY")

if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    print("WARNING: Missing Supabase credentials! The service will not be able to sync.")

BASE_REST_URL = f"{(SUPABASE_URL or '').rstrip('/')}/rest/v1"
DEFAULT_HEADERS = {
    "apikey": SUPABASE_ANON_KEY,
    "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
}

app = FastAPI(title="Supabase Commit Sync API")
# Allow all origins for production access or specific ones if provided
FRONTEND_URL = os.getenv("FRONTEND_URL") or "http://localhost:5173"

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        FRONTEND_URL.rstrip("/")
    ],
    allow_credentials=True,  # Re-enabling because we are using specific origins now!
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/dashboard")
def dashboard() -> dict[str, Any]:
    sync_result = sync_commit_links()
    issues = get_rows(
        "req_code_mapping",
        "issue_id,title,status,issue_type,priority,project_key,assignee_email,reporter_email,commits,created_at,updated_at",
        order="updated_at.desc",
        limit=100,
    )
    events = get_rows(
        "extension_events",
        "id,event_type,developer_id,repository_name,timestamp,commit_id,branch,message,issue_id,additions,deletions,total_changes,author,author_email,attendance_pct",
        order="timestamp.desc",
        limit=100,
    )
    return {"sync": sync_result, "issues": issues, "events": events}


@app.post("/api/sync")
def sync_endpoint() -> dict[str, Any]:
    return sync_commit_links()


def sync_commit_links() -> dict[str, Any]:
    issues = get_rows(
        "req_code_mapping",
        "issue_id,title,description,commits",
        order="created_at.asc",
        limit=500,
    )
    events = get_rows(
        "extension_events",
        "commit_id,message,timestamp,files,files_json,diff_patch,repository_name,branch,issue_id",
        order="timestamp.asc",
        limit=500,
    )

    updates: list[dict[str, Any]] = []
    matched_issue_count = 0
    total_linked_commits = 0

    for issue in issues:
        matches = rank_issue_matches(issue, events)
        matched_commit_ids = [match["commit_id"] for match in matches]
        existing = issue.get("commits") or []

        if matched_commit_ids != existing:
            patch_row(
                "req_code_mapping",
                f"issue_id=eq.{parse.quote(str(issue['issue_id']))}",
                {"commits": matched_commit_ids},
            )

        if matched_commit_ids:
            matched_issue_count += 1
            total_linked_commits += len(matched_commit_ids)

        updates.append({"issue_id": issue["issue_id"], "commits": matched_commit_ids, "matches": matches})

    return {
        "updated_issues": len(updates),
        "matched_issues": matched_issue_count,
        "linked_commits": total_linked_commits,
        "updates": updates,
    }


def rank_issue_matches(issue: dict[str, Any], events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issue_id = str(issue.get("issue_id", ""))
    issue_text = " ".join(filter(None, [issue.get("title"), issue.get("description")]))
    issue_profile = build_issue_profile(issue_text)
    event_profiles = [build_event_profile(event) for event in events]
    ml_scores = compute_ml_scores(issue_profile["ml_text"], [profile["ml_text"] for profile in event_profiles])
    results: list[dict[str, Any]] = []

    for event, event_profile, ml_score in zip(events, event_profiles, ml_scores):
        score, reasons = score_event_match(issue_id, issue_profile, event_profile, event, ml_score)
        if score >= MIN_SCORE:
            results.append({"commit_id": event["commit_id"], "score": round(score, 2), "reasons": reasons})

    results.sort(key=lambda item: (-item["score"], item["commit_id"]))
    return results[:MAX_MATCHES_PER_ISSUE]


def compute_ml_scores(issue_text: str, event_texts: list[str]) -> list[float]:
    if not event_texts:
        return []

    documents = [issue_text, *event_texts]
    vectorizer = TfidfVectorizer(ngram_range=(1, 2), stop_words="english", sublinear_tf=True, min_df=1)
    matrix = vectorizer.fit_transform(documents)
    similarities = sklearn_cosine_similarity(matrix[0:1], matrix[1:]).flatten()
    return [float(score) for score in similarities]


def score_event_match(
    issue_id: str,
    issue_profile: dict[str, Any],
    event_profile: dict[str, Any],
    event: dict[str, Any],
    ml_similarity: float,
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    explicit_issue_id = str(event.get("issue_id") or "")

    if explicit_issue_id and explicit_issue_id.lower() == issue_id.lower():
        score += 12.0
        reasons.append("explicit issue_id match")

    if ml_similarity > 0:
        ml_score = ml_similarity * 18.0
        score += ml_score
        reasons.append(f"ml nlp similarity: {ml_similarity:.2f}")

    overlap = issue_profile["tokens"] & event_profile["tokens"]
    significant_overlap = [token for token in overlap if token not in COMMON_CODE_WORDS]
    if significant_overlap:
        overlap_score = min(sum(token_weight(token) for token in significant_overlap), 6.5)
        score += overlap_score
        reasons.append(f"token overlap: {', '.join(sorted(significant_overlap)[:6])}")

    code_overlap = issue_profile["code_tokens"] & event_profile["code_tokens"]
    if code_overlap:
        code_score = min(sum(token_weight(token) for token in code_overlap), 5.0)
        score += code_score
        reasons.append(f"code overlap: {', '.join(sorted(code_overlap)[:6])}")

    filename_bonus = score_filename_matches(issue_profile["tokens"], event_profile["file_paths"])
    if filename_bonus:
        score += filename_bonus
        reasons.append("filename aligns with issue text")

    phrase_bonus = score_phrase_matches(issue_profile["normalized_text"], event_profile["combined_lower"])
    if phrase_bonus:
        score += phrase_bonus
        reasons.append("shared issue/code phrases")

    pattern_bonus = score_code_patterns(issue_profile, event_profile)
    if pattern_bonus:
        score += pattern_bonus
        reasons.append("code pattern support")

    if not significant_overlap and not code_overlap and ml_similarity < 0.12 and phrase_bonus == 0:
        score = 0.0

    return score, reasons


def build_issue_profile(issue_text: str) -> dict[str, Any]:
    normalized_text = normalize_spaces(issue_text.lower())
    tokens = tokenize_text(issue_text)
    code_tokens = extract_code_like_tokens(issue_text)

    return {
        "normalized_text": normalized_text,
        "tokens": set(tokens),
        "code_tokens": set(code_tokens),
        "ml_text": build_ml_text(issue_text, tokens, code_tokens),
    }


def build_event_profile(event: dict[str, Any]) -> dict[str, Any]:
    files = event.get("files") or []
    file_paths = [str(file.get("file_path", "")) for file in files]
    patch_chunks = [str(file.get("patch", "")) for file in files]
    message_text = str(event.get("message", ""))
    branch_text = str(event.get("branch", ""))
    repo_text = str(event.get("repository_name", ""))
    string_literals = extract_string_literals("\n".join(patch_chunks))
    identifiers = extract_identifiers("\n".join(patch_chunks))
    added_lines = extract_added_lines(patch_chunks)

    combined_text = "\n".join(
        [message_text, branch_text, repo_text, " ".join(file_paths), " ".join(string_literals), " ".join(identifiers), " ".join(added_lines), "\n".join(patch_chunks)]
    )

    text_tokens = tokenize_text(combined_text)
    code_tokens = extract_code_like_tokens(" ".join([" ".join(file_paths), " ".join(identifiers), " ".join(string_literals), " ".join(added_lines)]))

    return {
        "file_paths": file_paths,
        "combined_lower": combined_text.lower(),
        "patch_chunks": patch_chunks,
        "tokens": set(text_tokens),
        "code_tokens": set(code_tokens),
        "ml_text": build_ml_text(combined_text, text_tokens, code_tokens),
    }


def build_ml_text(source_text: str, tokens: list[str], code_tokens: list[str]) -> str:
    weighted_text = [source_text]
    weighted_text.extend(tokens)
    weighted_text.extend(code_tokens)
    weighted_text.extend(code_tokens)
    return " ".join(weighted_text)


def tokenize_text(text: str) -> list[str]:
    raw_tokens = re.findall(r"[A-Za-z0-9_]+", text)
    expanded_tokens: list[str] = []
    for token in raw_tokens:
        expanded_tokens.extend(split_identifier(token))
    normalized = [normalize_token(token) for token in expanded_tokens]
    return [token for token in normalized if token and token not in STOP_WORDS]


def extract_code_like_tokens(text: str) -> list[str]:
    identifiers = extract_identifiers(text)
    string_literals = extract_string_literals(text)
    tokens: list[str] = []
    for item in identifiers + string_literals:
        tokens.extend(tokenize_text(item))
    return tokens


def extract_identifiers(text: str) -> list[str]:
    identifiers = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text)
    return [identifier for identifier in identifiers if identifier.lower() not in STOP_WORDS]


def extract_string_literals(text: str) -> list[str]:
    matches = re.findall(r'"([^"\\]{2,})"|\'([^\'\\]{2,})\'', text)
    values: list[str] = []
    for left, right in matches:
        literal = left or right
        if literal:
            values.append(literal)
    return values


def extract_added_lines(patch_chunks: list[str]) -> list[str]:
    lines: list[str] = []
    for chunk in patch_chunks:
        for line in chunk.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                lines.append(line[1:].strip())
    return lines


def split_identifier(token: str) -> list[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", token.replace("_", " ").replace("-", " "))
    return [part for part in spaced.split() if part]


def normalize_token(token: str) -> str:
    lowered = token.lower()
    lowered = re.sub(r"[^a-z0-9]+", "", lowered)
    if len(lowered) <= 2:
        return ""
    for suffix in ("ing", "ers", "ies", "ied", "er", "ed", "es", "s"):
        if lowered.endswith(suffix) and len(lowered) - len(suffix) >= 3:
            return lowered[: -len(suffix)] + ("y" if suffix in {"ies", "ied"} else "")
    return lowered


def score_filename_matches(issue_tokens: set[str], file_paths: list[str]) -> float:
    if not issue_tokens or not file_paths:
        return 0.0
    normalized_paths = [path.lower() for path in file_paths if path and not path.lower().startswith(".devpulse/")]
    if not normalized_paths:
        return 0.0

    score = 0.0
    for token in issue_tokens:
        for path in normalized_paths:
            filename = path.split("/")[-1]
            if token in filename:
                score += 2.0
                break
    return min(score, 5.0)


def score_phrase_matches(issue_text_lower: str, combined_lower: str) -> float:
    score = 0.0
    quoted_phrases = re.findall(r'"([^\"]+)"', issue_text_lower)
    for phrase in quoted_phrases:
        phrase = normalize_spaces(phrase)
        if phrase and phrase in normalize_spaces(combined_lower):
            score += 4.0

    issue_bigrams = extract_ngrams(issue_text_lower, 2)
    event_bigrams = extract_ngrams(combined_lower, 2)
    shared_bigrams = issue_bigrams & event_bigrams
    score += min(len(shared_bigrams) * 1.25, 4.0)
    return score


def score_code_patterns(issue_profile: dict[str, Any], event_profile: dict[str, Any]) -> float:
    score = 0.0
    patch_text = "\n".join(event_profile["patch_chunks"]).lower()
    issue_tokens = issue_profile["tokens"]

    if "print" in issue_tokens and "print(" in patch_text:
        score += 2.0
    if "name" in issue_tokens and re.search(r'print\(("|\').+("|\')\)', patch_text):
        score += 2.5
    if issue_tokens & SORT_TERMS:
        sort_hits = sum(1 for term in SORT_TERMS if term in patch_text)
        score += min(sort_hits * 1.6, 4.8)
    if ("create" in issue_tokens or "file" in issue_tokens) and "new file mode" in patch_text:
        score += 1.5

    return score


def extract_ngrams(text: str, size: int) -> set[str]:
    tokens = tokenize_text(text)
    if len(tokens) < size:
        return set()
    return {" ".join(tokens[index : index + size]) for index in range(len(tokens) - size + 1)}


def token_weight(token: str) -> float:
    if token.isdigit():
        return 1.0
    if token in SORT_TERMS:
        return 2.4
    if len(token) >= 9:
        return 2.6
    if len(token) >= 6:
        return 2.1
    if len(token) >= 4:
        return 1.6
    return 1.2


def normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def get_rows(table: str, select: str, order: Optional[str] = None, limit: Optional[int] = None) -> list[dict[str, Any]]:
    params = {"select": select}
    if order:
        params["order"] = order
    if limit:
        params["limit"] = str(limit)
    query = parse.urlencode(params, safe="*,()")
    response = request_json("GET", f"{BASE_REST_URL}/{table}?{query}")
    if not isinstance(response, list):
        raise HTTPException(status_code=500, detail=f"Unexpected response for {table}")
    return response


def patch_row(table: str, filters: str, payload: dict[str, Any]) -> Any:
    headers = {
        **DEFAULT_HEADERS,
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    return request_json("PATCH", f"{BASE_REST_URL}/{table}?{filters}", payload=payload, headers=headers)


def request_json(method: str, url: str, payload: Optional[Any] = None, headers: Optional[dict[str, str]] = None) -> Any:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = request.Request(url, method=method, headers=headers or DEFAULT_HEADERS, data=data)
    try:
        with request.urlopen(req, timeout=30) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else None
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise HTTPException(status_code=exc.code, detail=detail) from exc
    except error.URLError as exc:
        raise HTTPException(status_code=502, detail=str(exc.reason)) from exc
