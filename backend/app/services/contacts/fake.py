import re
from datetime import UTC, datetime

from app.models.enums import EmailSource, VerificationStatus
from app.services.contacts.base import (
    ContactProvider,
    ContactProviderAuthError,
    EmailResult,
    PeopleSearch,
    PersonCandidate,
)

# (first, last, title, department, seniority, verification status in the search results)
FakePerson = tuple[str, str, str, str, str, str | None]

DEFAULT_PEOPLE: list[FakePerson] = [
    ("Asha", "Rao", "Co-founder & CTO", "executive", "executive", "valid"),
    ("Vikram", "Iyer", "Engineering Manager", "it", "senior", "valid"),
    ("Neha", "Kapoor", "Technical Recruiter", "hr", "senior", "accept_all"),
    ("Rahul", "Menon", "Senior Software Engineer", "it", "senior", None),
]


def verification_for(email: str) -> VerificationStatus:
    """The fake's deliverability rule: local parts containing 'invalid' or 'bounce' are invalid,
    'catchall' is accept_all, 'unknown' is unknown, anything else valid."""
    local = email.split("@", 1)[0].lower()
    if "invalid" in local or "bounce" in local:
        return VerificationStatus.INVALID
    if "catchall" in local:
        return VerificationStatus.ACCEPT_ALL
    if "unknown" in local:
        return VerificationStatus.UNKNOWN
    return VerificationStatus.VALID


class FakeContactProvider(ContactProvider):
    """Deterministic people for any company (USE_FAKES=true and tests). `calls` records every call so
    caching can be asserted; `people` and `headcount` can be replaced per test."""

    name = "fake"

    def __init__(
        self,
        people: list[FakePerson] | None = None,
        headcount: str | None = "11-50",
        rejected: bool = False,
        resolve_names: bool = True,
    ) -> None:
        """`resolve_names=False` doesn't report a domain for name-only searches, so a fake run
        against a real dev database never writes made-up domains onto companies."""
        self.people = list(DEFAULT_PEOPLE if people is None else people)
        self.headcount = headcount
        self.rejected = rejected
        self.resolve_names = resolve_names
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def _check(self) -> None:
        if self.rejected:
            raise ContactProviderAuthError("fake: key rejected")

    async def search_people(self, *, domain: str | None = None, company: str | None = None) -> PeopleSearch:
        self.calls.append(("search_people", (domain or "", company or "")))
        self._check()
        reported = domain or (self._slug(company) if self.resolve_names else None)
        domain = domain or self._slug(company)
        now = datetime.now(UTC)
        return PeopleSearch(
            domain=reported,
            organization=company,
            headcount=self.headcount,
            people=[
                PersonCandidate(
                    full_name=f"{first} {last}",
                    first_name=first,
                    last_name=last,
                    title=title,
                    department=department,
                    seniority=seniority,
                    email=f"{first.lower()}@{domain}",
                    confidence=90,
                    verification=VerificationStatus(status) if status else None,
                    verified_at=now if status else None,
                    source=EmailSource.HUNTER,
                )
                for first, last, title, department, seniority, status in self.people
            ],
        )

    @staticmethod
    def _slug(company: str | None) -> str:
        return re.sub(r"[^a-z0-9]+", "", (company or "").lower()) + ".example"

    async def find_email(self, domain: str, first_name: str, last_name: str) -> EmailResult:
        self.calls.append(("find_email", (domain, first_name, last_name)))
        self._check()
        email = f"{first_name.lower()}@{domain}"
        return EmailResult(email=email, confidence=90, verification=None, source=EmailSource.HUNTER)

    async def verify(self, email: str) -> VerificationStatus:
        self.calls.append(("verify", (email,)))
        self._check()
        return verification_for(email)

    async def check_key(self) -> None:
        self.calls.append(("check_key", ()))
        self._check()
