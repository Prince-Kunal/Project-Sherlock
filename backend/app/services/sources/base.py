import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.models.enums import AtsType, JobSourceType


class CompanyRef(BaseModel):
    """A company to poll via its ATS board."""

    id: uuid.UUID
    name: str
    domain: str | None = None
    ats_type: AtsType
    ats_token: str | None = None


class JobQuery(BaseModel):
    """An aggregator search (Adzuna, HN), built from a user's target roles."""

    what: str
    where: str | None = None
    max_days_old: int = 14


class RawJob(BaseModel):
    source: JobSourceType
    external_id: str | None
    payload: dict[str, Any]
    company_name: str | None = None  # aggregators: the posting's company, since there's no CompanyRef


class JobIn(BaseModel):
    """A normalised posting, ready to upsert into `jobs`."""

    source: JobSourceType
    external_id: str | None
    company_name: str
    company_domain: str | None = None
    title: str
    location: str | None = None
    remote: bool | None = None
    employment_type: str | None = None
    description_text: str = ""
    url: str | None = None
    posted_at: datetime | None = None


class JobSource(ABC):
    source: JobSourceType

    @abstractmethod
    async def fetch(self, target: CompanyRef | JobQuery) -> list[RawJob]: ...

    @abstractmethod
    def normalize(self, raw: RawJob) -> JobIn: ...
