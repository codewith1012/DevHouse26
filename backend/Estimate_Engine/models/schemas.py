from enum import Enum

from pydantic import BaseModel, Field


class EstimateStatus(str, Enum):
    CREATED = "created"
    UPDATED = "updated"


class EstimateCreateRequest(BaseModel):
    requirement: str = Field(..., min_length=10, description="Raw product or engineering requirement")


class HeuristicResult(BaseModel):
    complexity_score: float
    detected_features: list[str]
    estimated_hours: float
    rationale: str


class EstimateTask(BaseModel):
    task: str
    hours: float
    source: str


class AdaptiveWeights(BaseModel):
    heuristic_weight: float
    llm_weight: float
    reason: str


class LLMEstimate(BaseModel):
    estimated_hours: float
    confidence: float
    breakdown: list[EstimateTask]
    summary: str


class EstimateResponse(BaseModel):
    id: str
    requirement: str
    estimated_hours: float
    confidence: float
    breakdown: dict
    status: EstimateStatus


class IssueEstimateResponse(BaseModel):
    issue_id: str
    title: str
    requirement: str
    heuristic_score: float
    llm_score: float
    final_score: float
    confidence: float
    uncertainty: str
    estimate_breakdown: list[EstimateTask]
    breakdown: dict
    status: EstimateStatus


class CommitSignalRequest(BaseModel):
    issue_id: str
    commit_sha: str
    commit_message: str = ""
    changed_files: list[str] = Field(default_factory=list)
    files_added: int = 0
    files_deleted: int = 0
    lines_added: int = 0
    lines_deleted: int = 0
    tests_changed: int = 0


class PullRequestSignalRequest(BaseModel):
    issue_id: str
    pr_number: int | None = None
    title: str
    review_comments: int = 0
    review_rounds: int = 0
    lines_added: int = 0
    lines_deleted: int = 0
    changed_files: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    is_reopened: bool = False


class TestFailureSignalRequest(BaseModel):
    issue_id: str
    suite: str = "default"
    failed_tests: int = 0
    failing_files: list[str] = Field(default_factory=list)
    error_types: list[str] = Field(default_factory=list)
    severity: str = "medium"


class ReworkSignalRequest(BaseModel):
    issue_id: str
    reason: str
    reopened: bool = True
    review_comments: int = 0
    changed_files: list[str] = Field(default_factory=list)


class ExtensionCommitFile(BaseModel):
    file_path: str
    file_extension: str = ""
    change_type: str = "modified"
    additions: int = 0
    deletions: int = 0
    language: str = "text"
    patch: str = ""
    module: str = ""
    directory: str = ""
    commit_id: str = ""


class ExtensionEventRequest(BaseModel):
    event_type: str
    schema_version: str
    developer_id: str
    commit_id: str
    author: str
    author_email: str
    message: str
    repository_owner: str | None = None
    repository_name: str
    timestamp: str
    branch: str
    additions: int = 0
    deletions: int = 0
    commit_type: str
    parent_commit_id: str | None = None
    commit_category: str
    commit_message_length: int = 0
    total_changes: int = 0
    commit_size: int = 0
    is_merge_commit: bool = False
    linked_issue: str | None = None
    issue_id: str | None = None
    pull_request_number: int | None = None
    pr_title: str | None = None
    pr_labels: list[str] = Field(default_factory=list)
    files: list[ExtensionCommitFile] = Field(default_factory=list)
    files_changed_count: int | None = None
    net_loc: int | None = None
    diff_patch: str | None = None
    files_json: dict | None = None
    modules_touched: list[str] = Field(default_factory=list)
    attendance_pct: float | None = None
    presence_total_checks: int | None = None
    presence_present_count: int | None = None
    session_duration_secs: int | None = None
    session_start: str | None = None
    active_minutes: int = 0
    idle_minutes: int = 0
    focus_ratio: float = 1.0
    debug_session_count: int = 0


class DevelopmentSignalResponse(BaseModel):
    id: str
    issue_id: str
    signal_type: str
    source: str
    payload: dict
    created_at: str


class FeedbackRecord(BaseModel):
    id: str | None = None
    issue_id: str
    heuristic_score: float
    llm_score: float
    predicted_score: float
    actual_effort_proxy: float
    absolute_error: float
    relative_error: float
    signal_count: int
    issue_duration_hours: float
    created_at: str


class FeedbackCloseRequest(BaseModel):
    issue_id: str
    status: str = "done"
    actual_hours: float | None = None


class FeedbackSummary(BaseModel):
    total_samples: int
    avg_absolute_error: float
    avg_relative_error: float
    avg_actual_effort_proxy: float
    adaptive_weights: AdaptiveWeights


class EstimateHistoryEntry(BaseModel):
    id: str | None = None
    issue_id: str
    previous_score: float
    updated_score: float
    delta_score: float
    change_reason: str
    drift_level: str
    signal_type: str
    signal_id: str | None = None
    changed_at: str


class CommitImpactResult(BaseModel):
    impact_score: float
    delta_hours: float
    drift_level: str
    change_reason: str
    affected_areas: list[str]
    risk_factors: list[str]


class PollResult(BaseModel):
    processed_events: int
    skipped_events: int
    details: list[str]


class PollStatus(BaseModel):
    pending_events: int
    pending_event_ids: list[str]
    recent_processed_signal_ids: list[str]
    recent_processed_signals: list[DevelopmentSignalResponse]


class DashboardResponse(BaseModel):
    issue_id: str
    current_estimate: IssueEstimateResponse | None
    drift_level: str
    feedback_error: FeedbackRecord | None
    feedback_summary: FeedbackSummary
    recent_signal_timeline: list[DevelopmentSignalResponse]
    estimate_history: list[EstimateHistoryEntry]
    poll_status: PollStatus


class CommitUpdateRequest(BaseModel):
    estimate_id: str
    commit_message: str = ""
    changed_files: list[str] = Field(default_factory=list)


class EstimateUpdateResponse(BaseModel):
    id: str
    status: EstimateStatus
    updated_estimated_hours: float
    change_summary: str


class CommitEstimateResponse(BaseModel):
    issue_id: str
    commit_sha: str
    signal: DevelopmentSignalResponse
    impact: CommitImpactResult
    estimate: IssueEstimateResponse
