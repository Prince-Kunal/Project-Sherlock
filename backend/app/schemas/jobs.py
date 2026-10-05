import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.models import Company, Job
from app.models.enums import AtsType, SizeHint


class CompanyBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    domain: str | None


class JobOut(BaseModel):
    id: uuid.UUID
    title: str
    company: CompanyBrief
    location: str | None
    remote: bool | None
    employment_type: str | None
    url: str | None
    source: str
    posted_at: datetime | None
    first_seen_at: datetime
    effective_date: datetime  # posted_at if known, else first_seen_at
    age_days: int

    @classmethod
    def from_row(cls, job: Job, company: Company, now: datetime) -> "JobOut":
        effective = job.posted_at or job.first_seen_at
        return cls(
            id=job.id,
            title=job.title,
            company=CompanyBrief.model_validate(company),
            location=job.location,
            remote=job.remote,
            employment_type=job.employment_type,
            url=job.url,
            source=job.source.value,
            posted_at=job.posted_at,
            first_seen_at=job.first_seen_at,
            effective_date=effective,
            age_days=max(0, (now - effective).days),
        )


class JobFeed(BaseModel):
    items: list[JobOut]
    total: int
    max_age_days: int  # the age limit actually applied


EmploymentFilter = Literal["internship", "full_time", "part_time", "contract"]


class ManualJobIn(BaseModel):
    url: HttpUrl


class CompanyIn(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    domain: str | None = Field(None, max_length=255)
    ats_type: AtsType = AtsType.NONE
    ats_token: str | None = Field(None, max_length=255)
    size_hint: SizeHint = SizeHint.UNKNOWN


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    domain: str | None
    ats_type: AtsType
    ats_token: str | None
    size_hint: SizeHint
    last_polled_at: datetime | None
    active_jobs: int = 0
    jobs_on_board: int | None = None  # set when a board was verified on creation
