import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import api_error
from app.core.auth import AdminUser
from app.core.db import get_session
from app.models import AllowedEmail, Company, Job, User
from app.models.enums import AtsType
from app.schemas.jobs import CompanyIn, CompanyOut
from app.schemas.settings import AllowedEmailIn, AllowedEmailOut
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
