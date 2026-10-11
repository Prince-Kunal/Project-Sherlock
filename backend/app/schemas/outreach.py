"""Outreach API schemas. Phase 5 covers the contact step; Phase 6 adds drafts and review."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.enums import CampaignType, EmailSource, OutreachStatus, RoleCategory, VerificationStatus
from app.schemas.jobs import CompanyBrief, JobOut
from app.schemas.tailor import ResumeChange
from app.services.resume.ats_check import AtsReport, KeywordCoverage


class EmailDraft(BaseModel):
    """LLM contract for prompts/draft_email.md (PLAN.md §6). `body` is only the middle of the email:
    the greeting, opt-out line and signature are added in code, so the model never sees the user's
    name or links (§3.1) and the opt-out line is always present (invariant 9)."""

    subject: str
    body: str
    personalization_source: str  # verbatim sentence from the supplied context the hook is based on


DraftIssueCode = Literal[
    "subject_empty",
    "subject_too_long",
    "too_long",
    "no_opt_out",
    "placeholder",
    "unknown_source",
    "no_attachment_mention",
    "greeting_or_signoff",
]


class DraftIssue(BaseModel):
    code: DraftIssueCode
    message: str


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    title: str | None
    email: str
    role_category: RoleCategory
    verification_status: VerificationStatus  # accept_all gets a warning badge in the UI
    email_source: EmailSource


class OutreachOut(BaseModel):
    id: uuid.UUID
    status: OutreachStatus
    campaign_type: CampaignType
    job_id: uuid.UUID | None
    company: CompanyBrief
    contact: ContactOut | None
    failure_reason: str | None
    failure_message: str | None = None  # the human-readable detail of the last failure
    created_at: datetime


class ManualContactIn(BaseModel):
    email: EmailStr
    full_name: str | None = Field(None, max_length=300)
    title: str | None = Field(None, max_length=300)


class OutreachListItem(OutreachOut):
    """A row in the review queue or tracker."""

    subject: str | None
    job_title: str | None
    fit_score: int | None
    updated_at: datetime


class OutreachDetail(OutreachListItem):
    """Everything the review card shows."""

    body: str | None
    personalization_source: str | None
    match_id: uuid.UUID | None
    job: JobOut | None
    matched_skills: list[str]
    missing_skills: list[str]
    resume_pdf_url: str | None
    resume_filename: str | None
    resume_diff: list[ResumeChange]
    keyword_coverage: KeywordCoverage | None
    ats: AtsReport | None
    approved_at: datetime | None


class OutreachList(BaseModel):
    items: list[OutreachListItem]
    total: int


class DraftEditIn(BaseModel):
    subject: str | None = Field(None, max_length=200)
    body: str | None = Field(None, max_length=5000)


class RegenerateIn(BaseModel):
    hint: str | None = Field(None, max_length=300)


class ReviewStats(BaseModel):
    pending_review: int
    new_matches: int
    sent_this_week: int
    daily_send_cap: int
    replies: int
    followups_due: int
    failed: int


class BuildQueued(BaseModel):
    queued: bool
