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


class CommitUpdateRequest(BaseModel):
    estimate_id: str
    commit_message: str = ""
    changed_files: list[str] = Field(default_factory=list)


class EstimateUpdateResponse(BaseModel):
    id: str
    status: EstimateStatus
    updated_estimated_hours: float
    change_summary: str
