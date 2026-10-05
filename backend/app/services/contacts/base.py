"""Contact provider interface (PLAN.md Phase 5): people search, email finding and verification.

Hunter is the implementation (hunter.py); Apollo can be added behind the same interface (Phase 8).
"""

from abc import ABC, abstractmethod
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import EmailSource, VerificationStatus


class PersonCandidate(BaseModel):
    full_name: str
    first_name: str | None = None
    last_name: str | None = None
    title: str | None = None
    department: str | None = None
    seniority: str | None = None
    email: str | None = None  # Hunter's domain search returns it; other providers may not
    confidence: int | None = None  # 0-100 where the provider reports it
    verification: VerificationStatus | None = None
    verified_at: datetime | None = None
    source: EmailSource


class PeopleSearch(BaseModel):
    domain: str | None  # the company's domain (resolved by the provider when searching by name)
    organization: str | None = None
    headcount: str | None = None  # e.g. "11-50"
    people: list[PersonCandidate] = Field(default_factory=list)


class EmailResult(BaseModel):
    email: str | None
    confidence: int | None = None
    verification: VerificationStatus | None = None
    source: EmailSource


class ContactProviderError(Exception):
    """The provider failed (network, unexpected response)."""


class ContactProviderAuthError(ContactProviderError):
    """The key was rejected or the account is restricted."""


class ContactQuotaError(ContactProviderError):
    """The account's monthly credits are used up."""


class ContactProvider(ABC):
    name: str

    @abstractmethod
    async def search_people(self, *, domain: str | None = None, company: str | None = None) -> PeopleSearch:
        """Decision-makers at a company (founders, engineering leads, recruiters), by domain or, when
        the domain is unknown, by company name. Costs one search credit."""

    @abstractmethod
    async def find_email(self, domain: str, first_name: str, last_name: str) -> EmailResult:
        """A specific person's address. Costs one search credit when found."""

    @abstractmethod
    async def verify(self, email: str) -> VerificationStatus:
        """Deliverability check. Costs one verification."""

    @abstractmethod
    async def check_key(self) -> None:
        """Raise ContactProviderAuthError if the key is unusable. Free (no credits)."""
