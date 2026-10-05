"""Outreach API schemas. Phase 5 covers the contact step; Phase 6 adds drafts and review."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.enums import CampaignType, EmailSource, OutreachStatus, RoleCategory, VerificationStatus
from app.schemas.jobs import CompanyBrief


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
