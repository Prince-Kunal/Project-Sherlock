import uuid
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import api_error
from app.core.auth import AdminUser
from app.core.config import get_settings
from app.core.db import get_session
from app.models import AllowedEmail, Company, Job, OutreachEvent, SuppressionEntry, UsageLedger, User
from app.models.enums import AtsType, OutreachEventType, SuppressionReason
from app.schemas.admin import (
    OperationUsage,
    SuppressionIn,
    SuppressionOut,
    SuppressionPage,
    UsageReport,
    UserUsage,
)
from app.schemas.jobs import CompanyIn, CompanyOut
from app.schemas.settings import AllowedEmailIn, AllowedEmailOut
from app.services.quotas import LLM_PROVIDERS, LOOKUP_OPERATIONS, month_start, quota_status
from app.services.registry import get_source_http
from app.services.sources.ashby import AshbySource
from app.services.sources.base import CompanyRef, JobSource
from app.services.sources.greenhouse import GreenhouseSource
from app.services.sources.http import PoliteHttpClient, SourceHTTPError
from app.services.sources.lever import LeverSource
from app.services.sources.text import normalize_domain
from app.workers.queue import enqueue

router = APIRouter(prefix="/admin", tags=["admin"])

Session = Annotated[AsyncSession, Depends(get_session)]


def _board_source(ats: AtsType, http: PoliteHttpClient) -> JobSource | None:
    if ats == AtsType.GREENHOUSE:
        return GreenhouseSource(http)
    if ats == AtsType.LEVER:
        return LeverSource(http)
    if ats == AtsType.ASHBY:
        return AshbySource(http)
    return None


@router.get("/companies", response_model=list[CompanyOut])
async def list_companies(_: AdminUser, session: Session) -> list[CompanyOut]:
    active = (
        select(Job.company_id, func.count().label("n"))
        .where(Job.is_active)
        .group_by(Job.company_id)
        .subquery()
    )
    rows = await session.execute(
        select(Company, func.coalesce(active.c.n, 0))
        .outerjoin(active, active.c.company_id == Company.id)
        .order_by(Company.name)
    )
    return [CompanyOut.model_validate(c).model_copy(update={"active_jobs": n}) for c, n in rows]


@router.post("/companies", response_model=CompanyOut, status_code=status.HTTP_201_CREATED)
async def add_company(
    body: CompanyIn,
    _: AdminUser,
    session: Session,
    http: Annotated[PoliteHttpClient, Depends(get_source_http)],
) -> CompanyOut:
    """Add a company to the registry. An ATS board is checked with one real request first."""
    domain = normalize_domain(body.domain)
    if body.ats_type != AtsType.NONE and not body.ats_token:
        raise api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "ats_token_required", "Give the board token.")
    clauses = []
    if domain:
        clauses.append(Company.domain == domain)
    if body.ats_token:
        clauses.append((Company.ats_type == body.ats_type) & (Company.ats_token == body.ats_token))
    if clauses:
        duplicate = await session.scalar(select(Company).where(or_(*clauses)).limit(1))
        if duplicate is not None:
            raise api_error(
                status.HTTP_409_CONFLICT, "company_exists", f"{duplicate.name} is already registered."
            )

    company = Company(
        id=uuid.uuid4(),
        name=body.name.strip(),
        domain=domain,
        ats_type=body.ats_type,
        ats_token=body.ats_token,
        size_hint=body.size_hint,
    )
    jobs_on_board = None
    source = _board_source(body.ats_type, http)
    if source is not None:
        ref = CompanyRef(id=company.id, name=company.name, ats_type=body.ats_type, ats_token=body.ats_token)
        try:
            jobs_on_board = len(await source.fetch(ref))
        except SourceHTTPError as exc:
            raise api_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "ats_board_not_found",
                f"No {body.ats_type.value} board answers for {body.ats_token!r} ({exc.status}).",
            ) from exc
    session.add(company)
    await session.commit()
    await session.refresh(company)
    return CompanyOut.model_validate(company).model_copy(update={"jobs_on_board": jobs_on_board})


class PollQueued(BaseModel):
    job_id: str | None


@router.post("/poll", response_model=PollQueued, status_code=status.HTTP_202_ACCEPTED)
async def trigger_poll(_: AdminUser) -> PollQueued:
    """Queue poll_sources on the worker now instead of waiting for the 6-hourly cron."""
    return PollQueued(job_id=await enqueue("poll_sources", job_id="poll_sources:manual"))


# --- Who may sign in (PLAN.md Phase 7: only allowlisted addresses) --------------------------------


@router.get("/allowed-emails", response_model=list[AllowedEmailOut])
async def list_allowed(_: AdminUser, session: Session) -> list[AllowedEmailOut]:
    rows = (await session.scalars(select(AllowedEmail).order_by(AllowedEmail.created_at))).all()
    users = set((await session.scalars(select(func.lower(User.email)))).all())
    return [
        AllowedEmailOut(email=r.email, created_at=r.created_at, signed_up=r.email.lower() in users)
        for r in rows
    ]


@router.post("/allowed-emails", response_model=AllowedEmailOut, status_code=status.HTTP_201_CREATED)
async def add_allowed(body: AllowedEmailIn, _: AdminUser, session: Session) -> AllowedEmailOut:
    email = body.email.strip().lower()
    row = await session.scalar(select(AllowedEmail).where(func.lower(AllowedEmail.email) == email))
    if row is None:
        row = AllowedEmail(email=email)
        session.add(row)
        await session.commit()
        await session.refresh(row)
    signed_up = await session.scalar(select(User.id).where(func.lower(User.email) == email)) is not None
    return AllowedEmailOut(email=row.email, created_at=row.created_at, signed_up=signed_up)


@router.delete("/allowed-emails/{email}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_allowed(email: str, admin: AdminUser, session: Session) -> None:
    """Stops future sign-ins only; an existing account stays until its data is deleted."""
    if email.lower() == admin.email.lower():
        raise api_error(status.HTTP_409_CONFLICT, "cannot_remove_self", "You can't remove yourself.")
    row = await session.scalar(select(AllowedEmail).where(func.lower(AllowedEmail.email) == email.lower()))
    if row is not None:
        await session.delete(row)
        await session.commit()


# --- Usage and costs (PLAN.md §13 and Phase 9) --------------------------------------------------------

VERIFY_OPERATIONS = ("hunter_verify",)


def _month_bounds(month: str | None) -> tuple[datetime, datetime]:
    start = datetime.strptime(month, "%Y-%m").replace(tzinfo=UTC) if month else month_start(datetime.now(UTC))
    end = (
        start.replace(year=start.year + 1, month=1)
        if start.month == 12
        else start.replace(month=start.month + 1)
    )
    return start, end


@router.get("/usage", response_model=UsageReport)
async def usage(
    _: AdminUser,
    session: Session,
    month: Annotated[str | None, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")] = None,
) -> UsageReport:
    """Per-user usage and estimated costs for one calendar month (UTC), from usage_ledger."""
    since, until = _month_bounds(month)
    ledger = (
        await session.execute(
            select(
                UsageLedger.user_id,
                UsageLedger.provider,
                UsageLedger.operation,
                func.sum(UsageLedger.units),
                func.sum(UsageLedger.est_cost_usd),
            )
            .where(UsageLedger.created_at >= since, UsageLedger.created_at < until)
            .group_by(UsageLedger.user_id, UsageLedger.provider, UsageLedger.operation)
        )
    ).all()
    sent_rows = await session.execute(
        select(OutreachEvent.user_id, func.count())
        .where(
            OutreachEvent.type.in_([OutreachEventType.SENT, OutreachEventType.FOLLOWUP_SENT]),
            OutreachEvent.created_at >= since,
            OutreachEvent.created_at < until,
        )
        .group_by(OutreachEvent.user_id)
    )
    sent = {user_id: count for user_id, count in sent_rows}

    per_user: dict[uuid.UUID, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    operations: dict[tuple[str, str], list[Decimal]] = defaultdict(lambda: [Decimal(0), Decimal(0)])
    for user_id, provider, operation, raw_units, raw_cost in ledger:
        units, cost = Decimal(raw_units or 0), Decimal(raw_cost or 0)
        row = per_user[user_id]
        if provider in LLM_PROVIDERS:
            row["llm_calls"] += units
            row["llm_usd"] += cost
        if operation in LOOKUP_OPERATIONS:
            row["contact_lookups"] += units
        if operation in VERIFY_OPERATIONS:
            row["contact_verifications"] += units
        row["cost"] += cost
        totals = operations[(provider.value, operation)]
        totals[0] += units
        totals[1] += cost

    current = since == month_start(datetime.now(UTC))
    users = []
    for user in (await session.scalars(select(User).order_by(User.created_at))).all():
        row = per_user[user.id]
        users.append(
            UserUsage(
                user_id=user.id,
                email=user.email,
                name=user.name,
                is_admin=user.is_admin,
                is_active=user.is_active,
                onboarded=user.onboarded_at is not None,
                joined_at=user.created_at,
                llm_calls=int(row["llm_calls"]),
                llm_usd=row["llm_usd"],
                contact_lookups=int(row["contact_lookups"]),
                contact_verifications=int(row["contact_verifications"]),
                est_cost_usd=row["cost"],
                sent=int(sent.get(user.id, 0)),
                quota_exceeded=(await quota_status(session, user.id)).exceeded if current else [],
            )
        )
    settings = get_settings()
    return UsageReport(
        month=since.strftime("%Y-%m"),
        since=since,
        until=until,
        contact_lookups_limit=settings.max_contact_lookups_per_user_month,
        llm_usd_limit=Decimal(str(settings.max_llm_usd_per_user_month)),
        users=users,
        operations=sorted(
            (
                OperationUsage(provider=p, operation=o, units=int(u), est_cost_usd=c)
                for (p, o), (u, c) in operations.items()
            ),
            key=lambda op: (op.provider, op.operation),
        ),
    )


# --- The global suppression list (invariants 3 and 9) -------------------------------------------------


@router.get("/suppression", response_model=SuppressionPage)
async def list_suppression(
    _: AdminUser,
    session: Session,
    q: Annotated[str | None, Query(max_length=320)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SuppressionPage:
    """Addresses nobody using Sherlock may email: opt-outs, bounces and manual entries. Read-only apart
    from manual additions; entries are never removed from the app."""
    query = select(SuppressionEntry)
    if q:
        query = query.where(SuppressionEntry.email.ilike(f"%{q.strip().lower()}%"))
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = (
        await session.scalars(query.order_by(SuppressionEntry.created_at.desc()).limit(limit).offset(offset))
    ).all()
    return SuppressionPage(
        items=[SuppressionOut(email=r.email, reason=r.reason, created_at=r.created_at) for r in rows],
        total=int(total or 0),
    )


@router.post("/suppression", response_model=SuppressionOut, status_code=status.HTTP_201_CREATED)
async def add_suppression(body: SuppressionIn, _: AdminUser, session: Session) -> SuppressionOut:
    """Add an address by hand (e.g. someone asked by phone not to be emailed). Idempotent."""
    email = body.email.strip().lower()
    row = await session.scalar(select(SuppressionEntry).where(func.lower(SuppressionEntry.email) == email))
    if row is None:
        row = SuppressionEntry(email=email, reason=SuppressionReason.MANUAL)
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return SuppressionOut(email=row.email, reason=row.reason, created_at=row.created_at)
