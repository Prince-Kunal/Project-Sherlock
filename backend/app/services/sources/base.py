import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from pydantic import BaseModel, field_validator

from app.models.enums import AtsType, JobSourceType
from app.services.sources.text import EmploymentType


class CompanyRef(BaseModel):
    """A company to poll via its ATS board."""

    id: uuid.UUID
    name: str
    domain: str | None = None
    ats_type: AtsType
    ats_token: str | None = None


class JobQuery(BaseModel):
    """An aggregator search (Adzuna), built from a user's target roles."""

    what: str
    where: str | None = None
    max_days_old: int = 14


class RawJob(BaseModel):
    source: JobSourceType
    external_id: str | None
    payload: dict[str, Any]
    company_name: str | None = None
    company_domain: str | None = None


class JobIn(BaseModel):
    """A normalised posting, ready to upsert into `jobs`."""

    source: JobSourceType
    external_id: str | None
    company_name: str
    company_domain: str | None = None
    title: str
    location: str | None = None
    remote: bool | None = None
    employment_type: EmploymentType | None = None
    description_text: str = ""
    url: str | None = None
    posted_at: datetime | None = None
    source_meta: dict[str, Any] | None = None

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("job has no title")
        return value[:300]

    @field_validator("location")
    @classmethod
    def _location(cls, value: str | None) -> str | None:
        value = " ".join((value or "").split())
        return value[:300] or None

    @field_validator("external_id")
    @classmethod
    def _external_id(cls, value: str | None) -> str | None:
        return value[:255] if value else None


class MalformedJobError(ValueError):
    """A source returned a posting we can't use (e.g. no title). It's skipped and counted as failed."""


class JobSource(ABC):
    source: JobSourceType

    @abstractmethod
    async def fetch(self, target: CompanyRef | JobQuery) -> list[RawJob]: ...

    @abstractmethod
    def normalize(self, raw: RawJob) -> JobIn: ...
