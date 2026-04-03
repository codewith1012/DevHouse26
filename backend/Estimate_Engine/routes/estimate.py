from fastapi import APIRouter, HTTPException

from database.repository import estimate_repository
from models.schemas import (
    CommitUpdateRequest,
    EstimateCreateRequest,
    EstimateResponse,
    IssueEstimateResponse,
    EstimateUpdateResponse,
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
