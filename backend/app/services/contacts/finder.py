"""Find the person to email about a job, with a deliverable address (PLAN.md Phase 5).

Order: HN contact hints (when the job came from HN) → contacts already known for the company (reused
for 60 days without calling the provider) → a fresh people search. Candidates are ranked by
selector.py and verified lazily; only `valid` or `accept_all` addresses are accepted.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, Contact, Job, SuppressionEntry
from app.models.enums import EmailSource, JobSourceType, SizeHint, VerificationStatus
from app.services.contacts.base import (
    ContactProvider,
    ContactProviderAuthError,
    ContactProviderError,
    ContactQuotaError,
    PersonCandidate,
)
from app.services.contacts.selector import Eligibility, categorize, is_startup, rank_contacts
from app.services.sources.text import company_domain_from_url, normalize_domain

log = logging.getLogger(__name__)

ACCEPTED = {VerificationStatus.VALID, VerificationStatus.ACCEPT_ALL}
VERIFICATION_TTL_DAYS = 60
MAX_VERIFICATIONS = 3  # per lookup: don't burn the month's verifications on one company


class NoContactError(Exception):
    """No usable contact. `reason` becomes the outreach's failure_reason."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass
class FinderUsage:
    searches: int = 0  # people searches + email finder calls (Hunter "searches")
    verifications: int = 0


def size_from_headcount(headcount: str | None) -> tuple[SizeHint, int | None]:
    """Hunter headcount ranges ("11-50", "1001-5000", "10K+") → size hint and an upper bound."""
    if not headcount:
        return SizeHint.UNKNOWN, None
    text = headcount.replace(",", "").upper().replace("K", "000").rstrip("+")
    try:
        upper = int(text.split("-")[-1])
    except ValueError:
        return SizeHint.UNKNOWN, None
    if upper <= 50:
        return SizeHint.STARTUP, upper
    return (SizeHint.MID if upper <= 500 else SizeHint.LARGE), upper


class ContactFinder:
    def __init__(
        self,
        provider: ContactProvider | None,
        *,
        now: datetime,
        cache_days: int = 60,
        searches_left: int | None = None,
    ) -> None:
        """`provider` None means no usable key: only contacts already in the database are used.
        `searches_left` caps provider searches (the user's monthly allowance)."""
        self._provider = provider
        self._now = now
        self._cache = timedelta(days=cache_days)
        self._searches_left = searches_left
        self.usage = FinderUsage()

    async def find(self, session: AsyncSession, company: Company, job: Job | None = None) -> Contact:
        try:
            return await self._find(session, company, job)
        except ContactQuotaError as exc:
            raise NoContactError("contact_quota", "Your Hunter credits for this month are used up.") from exc
        except ContactProviderAuthError as exc:
            raise NoContactError("contact_key_invalid", f"Hunter rejected the key: {exc}") from exc
        except ContactProviderError as exc:
            raise NoContactError("contact_provider_error", str(exc)) from exc

    async def _find(self, session: AsyncSession, company: Company, job: Job | None) -> Contact:
        suppressed = frozenset(
            e.lower() for e in (await session.scalars(select(SuppressionEntry.email))).all()
        )
        eligibility = Eligibility(suppressed=suppressed, now=self._now)

        # 1. Addresses the company posted itself on HN.
        if job is not None and job.source == JobSourceType.HN:
            for email in (job.source_meta or {}).get("contact_emails", []):
                contact = await self._upsert(
                    session,
                    company,
                    PersonCandidate(full_name=email.split("@", 1)[0], email=email, source=EmailSource.HN),
                )
                if eligibility.allows(contact) and await self._deliverable(contact):
                    return contact

        # 2. Known contacts while fresh, else 3. a new people search.
        fresh = (
            company.contacts_fetched_at is not None and self._now - company.contacts_fetched_at < self._cache
        )
        if not fresh and self._provider is not None:
            await self._search(session, self._provider, company, job)
        contacts = list(
            (await session.scalars(select(Contact).where(Contact.company_id == company.id))).all()
        )
        ranked = rank_contacts(contacts, startup=is_startup(company), eligibility=eligibility)
        for contact in ranked[:MAX_VERIFICATIONS]:
            if await self._deliverable(contact):
                return contact

        if not fresh and self._provider is None:
            raise NoContactError(
                "contact_key_required", "Add your Hunter API key in Settings to look up contacts."
            )
        raise NoContactError("no_contact", f"No suitable contact with a deliverable email at {company.name}.")

    async def _search(
        self, session: AsyncSession, provider: ContactProvider, company: Company, job: Job | None
    ) -> None:
        if self._searches_left is not None and self.usage.searches >= self._searches_left:
            raise NoContactError("contact_lookup_limit", "You've used this month's contact lookups.")
        domain = company.domain or company_domain_from_url(job.url if job else None)
        self.usage.searches += 1
        result = await provider.search_people(domain=domain, company=None if domain else company.name)
        found = normalize_domain(result.domain)
        if found and not company.domain and not await _domain_taken(session, found, company):
            company.domain = found
        if company.size_hint == SizeHint.UNKNOWN and company.employee_count is None:
            company.size_hint, company.employee_count = size_from_headcount(result.headcount)
        for person in result.people:
            if person.email:
                await self._upsert(session, company, person)
        company.contacts_fetched_at = self._now
        await session.flush()

    async def _upsert(self, session: AsyncSession, company: Company, person: PersonCandidate) -> Contact:
        email = (person.email or "").strip().lower()
        contact = await session.scalar(select(Contact).where(func.lower(Contact.email) == email))
        if contact is None:
            contact = Contact(company_id=company.id, email=email, email_source=person.source)
            session.add(contact)
        contact.full_name = person.full_name or contact.full_name or email
        contact.title = person.title or contact.title
        contact.department = person.department or contact.department
        contact.seniority = person.seniority or contact.seniority
        contact.confidence = person.confidence if person.confidence is not None else contact.confidence
        contact.role_category = categorize(contact.title, contact.seniority, contact.department)
        if person.verification is not None and (
            contact.verified_at is None or (person.verified_at and person.verified_at > contact.verified_at)
        ):
            contact.verification_status = person.verification
            contact.verified_at = person.verified_at or self._now
        await session.flush()
        return contact

    async def _deliverable(self, contact: Contact) -> bool:
        """Accept a recent valid/accept_all verification; otherwise verify (when a key is available)."""
        recent = contact.verified_at is not None and self._now - contact.verified_at < timedelta(
            days=VERIFICATION_TTL_DAYS
        )
        if recent and contact.verification_status in ACCEPTED:
            return True
        if recent and contact.verification_status == VerificationStatus.INVALID:
            return False
        if self._provider is None:
            return False
        self.usage.verifications += 1
        contact.verification_status = await self._provider.verify(contact.email)
        contact.verified_at = self._now
        return contact.verification_status in ACCEPTED


async def _domain_taken(session: AsyncSession, domain: str, company: Company) -> bool:
    other = await session.scalar(select(Company.id).where(Company.domain == domain, Company.id != company.id))
    return other is not None
