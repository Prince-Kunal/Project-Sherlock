from abc import ABC, abstractmethod

from pydantic import BaseModel

from app.models.enums import EmailSource, VerificationStatus


class PersonCandidate(BaseModel):
    full_name: str
    first_name: str
    last_name: str
    title: str | None = None
    department: str | None = None
    seniority: str | None = None
    email: str | None = None  # some providers return it directly from people search
    source: EmailSource


class EmailResult(BaseModel):
    email: str | None
    confidence: int | None = None  # 0-100 where the provider reports it
    source: EmailSource


class ContactProvider(ABC):
    """People search + email finding + verification (Hunter in Phase 5, Apollo in Phase 8)."""

    name: str

    @abstractmethod
    async def search_people(self, domain: str, titles: list[str]) -> list[PersonCandidate]: ...

    @abstractmethod
    async def find_email(self, domain: str, first_name: str, last_name: str) -> EmailResult: ...

    @abstractmethod
    async def verify(self, email: str) -> VerificationStatus: ...
