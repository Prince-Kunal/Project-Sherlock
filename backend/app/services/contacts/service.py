"""The contact step of the outreach pipeline (PLAN.md Phase 5), shared by the API and, from Phase 6,
the daily draft builder: create or reuse the job's outreach row, find a contact, or fail it with
`no_contact` (or a more specific reason) so the user can add one by hand."""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Company, Contact, Job, JobMatch, Outreach, SuppressionEntry, UsageLedger
from app.models.enums import (
    INACTIVE_OUTREACH_STATUSES,
    CampaignType,
    EmailSource,
    JobMatchStatus,
    OutreachEventType,
    OutreachStatus,
    UsageProvider,
)
from app.services.contacts.base import ContactProvider, ContactProviderAuthError, ContactQuotaError
from app.services.contacts.finder import ACCEPTED, ContactFinder, FinderUsage, NoContactError
from app.services.contacts.keys import resolve_hunter_key
from app.services.contacts.selector import COOLDOWN_DAYS, categorize
from app.services.email.state import record_event, transition

ProviderFactory = Callable[[str], ContactProvider]

SEARCH_OPERATION = "hunter_search"
VERIFY_OPERATION = "hunter_verify"


class OutreachConflictError(Exception):
    """Another outreach to this company is already active (invariant 4)."""


class ManualContactError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def contact_searches_this_month(session: AsyncSession, user_id: uuid.UUID, now: datetime) -> int:
    total = await session.scalar(
        select(func.coalesce(func.sum(UsageLedger.units), 0)).where(
            UsageLedger.user_id == user_id,
            UsageLedger.operation == SEARCH_OPERATION,
            UsageLedger.created_at >= month_start(now),
        )
    )
    return int(total or 0)


async def build_finder(
    session: AsyncSession, user_id: uuid.UUID, factory: ProviderFactory, now: datetime
) -> ContactFinder:
    settings = get_settings()
    key = await resolve_hunter_key(session, user_id)
    used = await contact_searches_this_month(session, user_id, now)
    return ContactFinder(
        factory(key) if key else None,
        now=now,
        cache_days=settings.contact_cache_days,
        searches_left=max(0, settings.max_contact_lookups_per_user_month - used),
    )


def record_contact_usage(session: AsyncSession, user_id: uuid.UUID, usage: FinderUsage) -> None:
    """Hunter credits spent (PLAN.md §13: log every paid call). Caller commits."""
    for operation, units in ((SEARCH_OPERATION, usage.searches), (VERIFY_OPERATION, usage.verifications)):
        if units:
            session.add(
                UsageLedger(user_id=user_id, provider=UsageProvider.HUNTER, operation=operation, units=units)
            )


async def start_job_outreach(
    session: AsyncSession, user_id: uuid.UUID, match: JobMatch, job: Job
) -> Outreach:
    """The active outreach for this job, a failed one retried, or a new one in `drafting`. Raises
    OutreachConflictError if a different outreach to the same company is active."""
    rows = (
        await session.scalars(
            select(Outreach)
            .where(Outreach.user_id == user_id, Outreach.company_id == job.company_id)
            .order_by(Outreach.created_at.desc())
        )
    ).all()
    active = next((o for o in rows if o.status not in INACTIVE_OUTREACH_STATUSES), None)
    if active is not None:
        if active.job_id != job.id:
            raise OutreachConflictError("an outreach to this company is already in progress")
        outreach = active
    elif (
        latest := next((o for o in rows if o.job_id == job.id), None)
    ) and latest.status == OutreachStatus.FAILED:
        await transition(session, latest, OutreachStatus.DRAFTING, actor_id=user_id)
        outreach = latest
    else:
        outreach = Outreach(
            user_id=user_id,
            campaign_type=CampaignType.JOB,
            job_id=job.id,
            company_id=job.company_id,
            status=OutreachStatus.DRAFTING,
        )
        session.add(outreach)
        try:
            await session.flush()
        except IntegrityError as exc:  # a concurrent request created one first
            raise OutreachConflictError("an outreach to this company is already in progress") from exc
    match.status = JobMatchStatus.IN_PIPELINE
    return outreach


async def find_contact_for(
    session: AsyncSession,
    outreach: Outreach,
    job: Job | None,
    company: Company,
    finder: ContactFinder,
    actor_id: uuid.UUID | None,
) -> Contact | None:
    """Attach the best contact, or move the outreach to `failed` with the reason. Caller commits."""
    if outreach.contact_id is not None:
        return await session.get(Contact, outreach.contact_id)
    try:
        contact = await finder.find(session, company, job)
    except NoContactError as exc:
        await transition(
            session, outreach, OutreachStatus.FAILED, actor_id=actor_id, failure_reason=exc.reason,
            payload={"message": str(exc)},
        )  # fmt: skip
        return None
    finally:
        record_contact_usage(session, outreach.user_id, finder.usage)
    outreach.contact_id = contact.id
    await record_event(
        session,
        outreach,
        OutreachEventType.CONTACT_CHANGED,
        {"contact_id": str(contact.id), "email": contact.email, "how": "found"},
    )
    return contact


async def set_contact_manually(
    session: AsyncSession,
    outreach: Outreach,
    *,
    email: str,
    full_name: str | None,
    title: str | None,
    factory: ProviderFactory,
    actor_id: uuid.UUID,
) -> Contact:
    """`POST /outreach/{id}/contact`: set or swap the contact after verifying the address. A failed
    outreach (e.g. `no_contact`) goes back to `drafting`. Caller commits."""
    if outreach.status not in (OutreachStatus.DRAFTING, OutreachStatus.FAILED, OutreachStatus.PENDING_REVIEW):
        raise ManualContactError("outreach_locked", "The contact can't be changed once a draft is approved.")
    email = email.strip().lower()
    now = datetime.now(UTC)
    if await session.scalar(select(SuppressionEntry.id).where(func.lower(SuppressionEntry.email) == email)):
        raise ManualContactError("suppressed", "This address asked not to be contacted.")
    contact = await session.scalar(select(Contact).where(func.lower(Contact.email) == email))
    if contact and contact.last_contacted_at and (now - contact.last_contacted_at).days < COOLDOWN_DAYS:
        raise ManualContactError(
            "contact_cooldown",
            f"Someone using Sherlock emailed this person in the last {COOLDOWN_DAYS} days.",
        )

    recent_ok = (
        contact is not None
        and contact.verification_status in ACCEPTED
        and contact.verified_at is not None
        and (now - contact.verified_at).days < 60
    )
    if not recent_ok:
        key = await resolve_hunter_key(session, outreach.user_id)
        if key is None:
            raise ManualContactError(
                "hunter_key_required", "Add your Hunter API key in Settings to verify emails."
            )
        try:
            status = await factory(key).verify(email)
        except ContactQuotaError as exc:
            raise ManualContactError(
                "contact_quota", "Your Hunter credits for this month are used up."
            ) from exc
        except ContactProviderAuthError as exc:
            raise ManualContactError("contact_key_invalid", "Hunter rejected your API key.") from exc
        record_contact_usage(session, outreach.user_id, FinderUsage(verifications=1))
        if status not in ACCEPTED:
            await session.commit()  # keep the usage row even though the address is refused
            raise ManualContactError(
                "email_not_deliverable", f"Hunter says this address is {status.value.replace('_', ' ')}."
            )
    else:
        status = contact.verification_status  # type: ignore[union-attr]

    if contact is None:
        contact = Contact(company_id=outreach.company_id, email=email, email_source=EmailSource.MANUAL)
        session.add(contact)
    contact.full_name = (full_name or "").strip() or contact.full_name or email.split("@", 1)[0]
    contact.title = (title or "").strip() or contact.title
    contact.role_category = categorize(contact.title, contact.seniority, contact.department)
    contact.verification_status = status
    contact.verified_at = contact.verified_at if recent_ok else now
    await session.flush()

    previous = outreach.contact_id
    outreach.contact_id = contact.id
    await record_event(
        session,
        outreach,
        OutreachEventType.CONTACT_CHANGED,
        {
            "contact_id": str(contact.id),
            "email": contact.email,
            "previous_contact_id": str(previous) if previous else None,
            "how": "manual",
            "actor": str(actor_id),
        },
    )
    if outreach.status == OutreachStatus.FAILED:
        await transition(session, outreach, OutreachStatus.DRAFTING, actor_id=actor_id)
    return contact
