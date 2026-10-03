from app.models.enums import EmailSource, VerificationStatus
from app.services.contacts.base import ContactProvider, EmailResult, PersonCandidate

_PEOPLE = [
    ("Asha", "Rao", "Co-founder & CTO", "engineering", "c_suite"),
    ("Vikram", "Iyer", "Engineering Manager", "engineering", "manager"),
    ("Neha", "Kapoor", "Technical Recruiter", "hr", "senior"),
    ("Rahul", "Menon", "Senior Software Engineer", "engineering", "senior"),
]


class FakeContactProvider(ContactProvider):
    """Deterministic people for any domain. Verification is driven by the address:
    local parts containing 'invalid' or 'bounce' are invalid, 'catchall' is accept_all, the rest valid.
    `calls` records every method call so caching can be asserted."""

    name = "fake"

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    async def search_people(self, domain: str, titles: list[str]) -> list[PersonCandidate]:
        self.calls.append(("search_people", (domain, *titles)))
        wanted = [t.lower() for t in titles]
        people = [
            PersonCandidate(
                full_name=f"{first} {last}",
                first_name=first,
                last_name=last,
                title=title,
                department=department,
                seniority=seniority,
                source=EmailSource.HUNTER,
            )
            for first, last, title, department, seniority in _PEOPLE
        ]
        if not wanted:
            return people
        return [p for p in people if any(w in (p.title or "").lower() for w in wanted)]

    async def find_email(self, domain: str, first_name: str, last_name: str) -> EmailResult:
        self.calls.append(("find_email", (domain, first_name, last_name)))
        return EmailResult(email=f"{first_name.lower()}@{domain}", confidence=90, source=EmailSource.HUNTER)

    async def verify(self, email: str) -> VerificationStatus:
        self.calls.append(("verify", (email,)))
        local = email.split("@", 1)[0].lower()
        if "invalid" in local or "bounce" in local:
            return VerificationStatus.INVALID
        if "catchall" in local:
            return VerificationStatus.ACCEPT_ALL
        return VerificationStatus.VALID
