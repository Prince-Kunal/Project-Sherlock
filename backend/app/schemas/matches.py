"""Job matching: the LLM scoring contract (PLAN.md §6 MatchResult) and the matches API."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import JobMatchStatus
from app.schemas.jobs import JobOut
from app.schemas.outreach import OutreachOut

MatchEmploymentType = Literal["internship", "full_time", "contract", "unknown"]


class MatchResult(BaseModel):
    fit_score: int = Field(ge=0, le=100)
    employment_type: MatchEmploymentType
    matched_skills: list[str] = Field(default_factory=list, max_length=25)
    missing_must_haves: list[str] = Field(default_factory=list, max_length=25)
    reasoning: str = Field(min_length=1, max_length=500)  # <= 2 sentences


class ScoredJob(MatchResult):
    """One item of a match.md batch response; `job_ref` echoes the ref given in the prompt."""

    job_ref: str


class ScoredJobLoose(BaseModel):
    """What a batch response is first validated as: items only need a ref, so one malformed item can
    be re-scored on its own (PLAN.md Phase 3) instead of failing the batch. Each item is then
    validated strictly as `ScoredJob` before anything is stored (invariant 7)."""

    model_config = ConfigDict(extra="allow")

    job_ref: str


class MatchOut(BaseModel):
    id: uuid.UUID
    job: JobOut
    fit_score: int | None
    embedding_score: float | None
    matched_skills: list[str]
    missing_skills: list[str]
    reasoning: str
    status: JobMatchStatus
    created_at: datetime
    outreach: OutreachOut | None = None  # the latest outreach for this job, if any


class ScoringStatus(BaseModel):
    llm_key_configured: bool
    calls_last_24h: int
    daily_limit: int


class MatchFeed(BaseModel):
    items: list[MatchOut]
    total: int
    min_score: int  # the minimum fit score actually applied
    scoring: ScoringStatus


MatchStatusFilter = Literal["active", "new", "shortlisted", "hidden", "in_pipeline", "expired"]
