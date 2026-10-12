"""Open outreach (PLAN.md Phase 8): prospect targets, the company-scoring contract (§6
CompanyMatchResult) and the company matches API."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models.enums import CompanyMatchStatus
from app.schemas.jobs import CompanyBrief
from app.schemas.outreach import OutreachOut

Chip = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
CompanySize = Literal["startup", "mid", "large"]


class CompanyMatchResult(BaseModel):
    fit_score: int = Field(ge=0, le=100)
    angle: str = Field(min_length=1, max_length=300)  # 1 sentence: why this user fits this company
    reasoning: str = Field(min_length=1, max_length=500)  # <= 2 sentences


class ScoredCompany(CompanyMatchResult):
    """One item of a match_company.md batch response; `company_ref` echoes the prompt's ref."""

    company_ref: str


class ScoredCompanyLoose(BaseModel):
    """Lenient first pass over a batch (only the ref is required); each item is then validated
    strictly as `ScoredCompany` (invariant 7)."""

    model_config = ConfigDict(extra="allow")

    company_ref: str


# --- API


class TargetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    target_roles: list[Chip] = Field(default_factory=list, max_length=10)
    contact_titles: list[Chip] = Field(default_factory=list, max_length=15)
    industries: list[Chip] = Field(default_factory=list, max_length=20)
    locations: list[Chip] = Field(default_factory=list, max_length=20)
    company_sizes: list[CompanySize] = Field(default_factory=list)
    include_companies: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    exclude_companies: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    is_active: bool = True


class TargetOut(BaseModel):
    id: uuid.UUID
    name: str
    target_roles: list[str]
    contact_titles: list[str]
    industries: list[str]
    locations: list[str]
    company_sizes: list[str]
    include_companies: list[CompanyBrief]
    exclude_companies: list[CompanyBrief]
    is_active: bool
    created_at: datetime


class CompanyCard(CompanyBrief):
    industry: str | None
    industry_tags: list[str]
    hq_location: str | None
    size_hint: str
    employee_count: int | None
    description: str | None
    has_website_text: bool


class CompanyMatchOut(BaseModel):
    id: uuid.UUID
    company: CompanyCard
    target_id: uuid.UUID | None
    target_name: str | None
    score: int
    angle: str
    reasoning: str
    status: CompanyMatchStatus
    created_at: datetime
    outreach: OutreachOut | None = None  # the latest outreach to this company, if any


class CompanyMatchFeed(BaseModel):
    items: list[CompanyMatchOut]
    total: int
    min_score: int


CompanyMatchFilter = Literal["active", "new", "queued", "contacted", "hidden"]


class ProspectOptions(BaseModel):
    """Suggestions for the target form."""

    industries: list[str]  # the most common industry tags among known companies
    sizes: list[CompanySize]
    companies_known: int


class NewCompanyIn(BaseModel):
    """A company to include by hand (it may not be in any directory)."""

    domain: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=255)]
    name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None = None


class RefreshQueued(BaseModel):
    queued: bool
