from fastapi import APIRouter, HTTPException

from database.repository import estimate_repository
from models.schemas import (
    CommitEstimateResponse,
    CommitSignalRequest,
    CommitUpdateRequest,
    DashboardResponse,
    FeedbackCloseRequest,
    FeedbackRecord,
    FeedbackSummary,
    ExtensionEventRequest,
    EstimateCreateRequest,
    EstimateHistoryEntry,
    EstimateResponse,
    IssueEstimateResponse,
    EstimateUpdateResponse,
    PollResult,
    PullRequestSignalRequest,
    ReworkSignalRequest,
    TestFailureSignalRequest,
)
from services.estimation_engine import estimation_engine


router = APIRouter(tags=["estimates"])


@router.post("/estimate", response_model=EstimateResponse)
async def create_estimate(payload: EstimateCreateRequest) -> EstimateResponse:
    return await estimation_engine.create_estimate(payload)


@router.post("/estimate/from-issue/{issue_id}", response_model=IssueEstimateResponse)
async def create_estimate_from_issue(issue_id: str) -> IssueEstimateResponse:
    try:
        return await estimation_engine.create_estimate_for_issue(issue_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/signals/commit", response_model=CommitEstimateResponse)
async def ingest_commit_signal(payload: CommitSignalRequest) -> CommitEstimateResponse:
    try:
        return await estimation_engine.process_commit_signal(payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/signals/extension", response_model=CommitEstimateResponse)
async def ingest_extension_signal(payload: ExtensionEventRequest) -> CommitEstimateResponse:
    try:
        return await estimation_engine.process_extension_event(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/signals/pr", response_model=IssueEstimateResponse)
async def ingest_pr_signal(payload: PullRequestSignalRequest) -> IssueEstimateResponse:
    try:
        return await estimation_engine.process_pr_signal(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/signals/test-failure", response_model=IssueEstimateResponse)
async def ingest_test_failure_signal(payload: TestFailureSignalRequest) -> IssueEstimateResponse:
    try:
        return await estimation_engine.process_test_failure_signal(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/signals/rework", response_model=IssueEstimateResponse)
async def ingest_rework_signal(payload: ReworkSignalRequest) -> IssueEstimateResponse:
    try:
        return await estimation_engine.process_rework_signal(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/estimate/history/{issue_id}", response_model=list[EstimateHistoryEntry])
def get_estimate_history(issue_id: str) -> list[EstimateHistoryEntry]:
    try:
        return estimation_engine.get_history_for_issue(issue_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/dashboard/{issue_id}", response_model=DashboardResponse)
def get_dashboard(issue_id: str) -> DashboardResponse:
    try:
        return estimation_engine.get_dashboard(issue_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/estimate/poll-extension-events", response_model=PollResult)
async def poll_extension_events() -> PollResult:
    try:
        return await estimation_engine.poll_extension_events()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/feedback/close-issue", response_model=FeedbackRecord)
async def close_feedback_loop(payload: FeedbackCloseRequest) -> FeedbackRecord:
    try:
        return await estimation_engine.close_feedback_loop(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/feedback/summary", response_model=FeedbackSummary)
def get_feedback_summary() -> FeedbackSummary:
    try:
        return estimation_engine.get_feedback_summary()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/estimate/{estimate_id}", response_model=EstimateResponse)
def get_estimate(estimate_id: str) -> EstimateResponse:
    record = estimate_repository.get(estimate_id)
    if not record:
        raise HTTPException(status_code=404, detail="Estimate not found")
    return record


@router.post("/update-from-commit", response_model=EstimateUpdateResponse)
def update_from_commit(payload: CommitUpdateRequest) -> EstimateUpdateResponse:
    record = estimate_repository.update_from_commit(payload)
    if not record:
        raise HTTPException(status_code=404, detail="Estimate not found")
    return record
