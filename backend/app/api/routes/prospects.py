"""Open outreach (PLAN.md Phase 8): prospect targets, the companies matched to them, and drafting from
a company match. Every query is scoped to the current user (invariant 5)."""

import uuid
from collections import Counter
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import api_error
from app.api.routes.outreach import run_pipeline
from app.core.auth import CurrentUser
from app.core.db import get_session
from app.models import Company, CompanyMatch, Outreach, ProspectTarget
from app.models.enums import CompanyMatchStatus, OutreachStatus
from app.schemas.jobs import CompanyBrief
from app.schemas.outreach import OutreachDetail
from app.schemas.prospects import (
    CompanyCard,
    CompanyMatchFeed,
    CompanyMatchFilter,
    CompanyMatchOut,
    NewCompanyIn,
    ProspectOptions,
    RefreshQueued,
    TargetIn,
    TargetOut,
)
from app.services.contacts.service import OutreachConflictError, ProviderFactory, start_open_outreach
from app.services.contacts.views import outreach_detail, outreach_out
from app.services.jobs.companies import find_or_create_company
from app.services.llm.client import LLMClient
from app.services.matching.pipeline import load_preferences
from app.services.registry import get_contact_provider_factory, get_llm_client
from app.services.sources.text import normalize_domain
from app.workers.queue import enqueue

router = APIRouter(prefix="/prospects", tags=["prospects"])

# Suggestions before any company has been discovered (the YC directory's most common industries).
COMMON_INDUSTRIES = [
    "b2b",
    "fintech",
    "developer tools",
    "artificial intelligence",
    "saas",
    "education",
    "healthcare",
    "consumer",
    "e-commerce",
    "security",
    "analytics",
    "infrastructure",
]

Session = Annotated[AsyncSession, Depends(get_session)]

_ACTIVE = (CompanyMatchStatus.NEW, CompanyMatchStatus.QUEUED, CompanyMatchStatus.CONTACTED)
_ACTIONS: dict[str, tuple[CompanyMatchStatus, tuple[CompanyMatchStatus, ...]]] = {
    "queue": (CompanyMatchStatus.QUEUED, (CompanyMatchStatus.NEW, CompanyMatchStatus.HIDDEN)),
    "hide": (CompanyMatchStatus.HIDDEN, (CompanyMatchStatus.NEW, CompanyMatchStatus.QUEUED)),
    "restore": (CompanyMatchStatus.NEW, (CompanyMatchStatus.QUEUED, CompanyMatchStatus.HIDDEN)),
}


# --- Targets ---------------------------------------------------------------------------------------


async def _briefs(session: AsyncSession, ids: list[uuid.UUID]) -> list[CompanyBrief]:
    if not ids:
        return []
    rows = {c.id: c for c in (await session.scalars(select(Company).where(Company.id.in_(ids)))).all()}
    return [CompanyBrief.model_validate(rows[i]) for i in ids if i in rows]


async def _target_out(session: AsyncSession, target: ProspectTarget) -> TargetOut:
    return TargetOut(
        id=target.id,
        name=target.name,
        target_roles=list(target.target_roles),
        contact_titles=list(target.contact_titles),
        industries=list(target.industries),
        locations=list(target.locations),
        company_sizes=list(target.company_sizes),
        include_companies=await _briefs(session, list(target.include_companies)),
        exclude_companies=await _briefs(session, list(target.exclude_companies)),
        is_active=target.is_active,
        created_at=target.created_at,
    )


async def _owned_target(session: AsyncSession, user_id: uuid.UUID, target_id: uuid.UUID) -> ProspectTarget:
    target = await session.scalar(
        select(ProspectTarget).where(ProspectTarget.id == target_id, ProspectTarget.user_id == user_id)
    )
    if target is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "target_not_found", "Target not found.")
    return target


async def _existing(session: AsyncSession, ids: list[uuid.UUID]) -> list[uuid.UUID]:
    """Keep only ids of companies that exist, in order, without duplicates."""
    if not ids:
        return []
    known = set((await session.scalars(select(Company.id).where(Company.id.in_(ids)))).all())
    return list(dict.fromkeys(i for i in ids if i in known))


async def _apply(session: AsyncSession, target: ProspectTarget, body: TargetIn) -> None:
    target.name = body.name
    target.target_roles = list(dict.fromkeys(body.target_roles))
    target.contact_titles = list(dict.fromkeys(body.contact_titles))
    target.industries = list(dict.fromkeys(body.industries))
    target.locations = list(dict.fromkeys(body.locations))
    target.company_sizes = list(dict.fromkeys(body.company_sizes))
    target.include_companies = await _existing(session, body.include_companies)
    target.exclude_companies = await _existing(session, body.exclude_companies)
    target.is_active = body.is_active


@router.get("/targets", response_model=list[TargetOut])
async def list_targets(user: CurrentUser, session: Session) -> list[TargetOut]:
    rows = (
        await session.scalars(
            select(ProspectTarget)
            .where(ProspectTarget.user_id == user.id)
            .order_by(ProspectTarget.created_at)
        )
    ).all()
    return [await _target_out(session, t) for t in rows]


@router.post("/targets", response_model=TargetOut, status_code=status.HTTP_201_CREATED)
async def create_target(body: TargetIn, user: CurrentUser, session: Session) -> TargetOut:
    target = ProspectTarget(user_id=user.id, name=body.name)
    await _apply(session, target, body)
    session.add(target)
    await session.commit()
    await session.refresh(target)
    return await _target_out(session, target)


@router.put("/targets/{target_id}", response_model=TargetOut)
async def update_target(
    target_id: uuid.UUID, body: TargetIn, user: CurrentUser, session: Session
) -> TargetOut:
    target = await _owned_target(session, user.id, target_id)
    await _apply(session, target, body)
    await session.commit()
    return await _target_out(session, target)


@router.delete("/targets/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_target(target_id: uuid.UUID, user: CurrentUser, session: Session) -> Response:
    """Delete a target. Its company matches stay (unlinked) so nothing already drafted is lost, but
    they're no longer drafted from."""
    target = await _owned_target(session, user.id, target_id)
    await session.delete(target)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/options", response_model=ProspectOptions)
async def options(user: CurrentUser, session: Session) -> ProspectOptions:
    """Industry suggestions for the target form: the most common tags among known companies."""
    tag_lists = (
        await session.scalars(select(Company.industry_tags).where(Company.domain.is_not(None)))
    ).all()
    counts = Counter(tag for tags in tag_lists for tag in tags)
    total = await session.scalar(select(func.count()).select_from(Company).where(Company.domain.is_not(None)))
    return ProspectOptions(
        industries=[tag for tag, _ in counts.most_common(60)] or COMMON_INDUSTRIES,
        sizes=["startup", "mid", "large"],
        companies_known=int(total or 0),
    )


@router.get("/companies/search", response_model=list[CompanyBrief])
async def search_companies(
    user: CurrentUser, session: Session, q: Annotated[str, Query(min_length=2, max_length=100)]
) -> list[CompanyBrief]:
    """Companies by name or domain, for the include/exclude pickers."""
    pattern = f"%{q.strip()}%"
    rows = (
        await session.scalars(
            select(Company)
            .where(
                Company.domain.is_not(None), or_(Company.name.ilike(pattern), Company.domain.ilike(pattern))
            )
            .order_by(func.length(Company.name), Company.name)
            .limit(10)
        )
    ).all()
    return [CompanyBrief.model_validate(c) for c in rows]


@router.post("/companies", response_model=CompanyBrief)
async def add_company(body: NewCompanyIn, user: CurrentUser, session: Session) -> CompanyBrief:
    """A company that isn't in any directory, by its website (its text is read on the next run)."""
    domain = normalize_domain(body.domain)
    if not domain or "." not in domain or " " in domain:
        raise api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "bad_domain", "Enter the company's website.")
    name = (body.name or "").strip() or domain.split(".")[0].capitalize()
    company = await find_or_create_company(session, name=name, domain=domain)
    await session.commit()
    return CompanyBrief.model_validate(company)


@router.post("/refresh", response_model=RefreshQueued, status_code=status.HTTP_202_ACCEPTED)
async def refresh(user: CurrentUser) -> RefreshQueued:
    """Find companies for this user's targets and score them now instead of waiting for the night."""
    job_id = await enqueue("discover_prospect_companies", str(user.id), job_id=f"discover:{user.id}")
    return RefreshQueued(queued=job_id is not None)


# --- Company matches -------------------------------------------------------------------------------


def _card(company: Company) -> CompanyCard:
    return CompanyCard(
        id=company.id,
        name=company.name,
        domain=company.domain,
        industry=company.industry,
        industry_tags=list(company.industry_tags or [])[:8],
        hq_location=company.hq_location,
        size_hint=company.size_hint.value,
        employee_count=company.employee_count,
        description=company.description,
        has_website_text=bool(company.website_text),
    )


async def _match_out(
    session: AsyncSession, match: CompanyMatch, company: Company, target: ProspectTarget | None
) -> CompanyMatchOut:
    latest = await session.scalar(
        select(Outreach)
        .where(Outreach.user_id == match.user_id, Outreach.company_id == match.company_id)
        .order_by(Outreach.created_at.desc())
        .limit(1)
    )
    return CompanyMatchOut(
        id=match.id,
        company=_card(company),
        target_id=match.prospect_target_id,
        target_name=target.name if target else None,
        score=match.score,
        angle=match.angle,
        reasoning=match.reasoning,
        status=match.status,
        created_at=match.created_at,
        outreach=await outreach_out(session, latest) if latest else None,
    )


async def _owned_match(
    session: AsyncSession, user_id: uuid.UUID, match_id: uuid.UUID
) -> tuple[CompanyMatch, Company, ProspectTarget | None]:
    row = (
        await session.execute(
            select(CompanyMatch, Company, ProspectTarget)
            .join(Company, Company.id == CompanyMatch.company_id)
            .outerjoin(ProspectTarget, ProspectTarget.id == CompanyMatch.prospect_target_id)
            .where(CompanyMatch.id == match_id, CompanyMatch.user_id == user_id)
        )
    ).first()
    if row is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "match_not_found", "Company match not found.")
    return row[0], row[1], row[2]


@router.get("/matches", response_model=CompanyMatchFeed)
async def list_company_matches(
    user: CurrentUser,
    session: Session,
    match_status: Annotated[CompanyMatchFilter, Query(alias="status")] = "active",
    min_score: Annotated[int | None, Query(ge=0, le=100)] = None,
    target_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CompanyMatchFeed:
    """Companies scored for the user, best first. Active (new, queued, contacted) by default, above
    the user's minimum fit score unless `min_score` says otherwise."""
    prefs = await load_preferences(session, user.id)
    floor = prefs.min_fit_score if min_score is None else min_score
    statuses = _ACTIVE if match_status == "active" else (CompanyMatchStatus(match_status),)
    conditions = [
        CompanyMatch.user_id == user.id,
        CompanyMatch.status.in_(statuses),
        CompanyMatch.score >= floor,
    ]
    if target_id is not None:
        conditions.append(CompanyMatch.prospect_target_id == target_id)
    total = await session.scalar(select(func.count()).select_from(CompanyMatch).where(*conditions)) or 0
    rows = (
        await session.execute(
            select(CompanyMatch, Company, ProspectTarget)
            .join(Company, Company.id == CompanyMatch.company_id)
            .outerjoin(ProspectTarget, ProspectTarget.id == CompanyMatch.prospect_target_id)
            .where(*conditions)
            .order_by(
                (CompanyMatch.status == CompanyMatchStatus.QUEUED).desc(),
                CompanyMatch.score.desc(),
                CompanyMatch.id,
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()
    items = [await _match_out(session, m, c, t) for m, c, t in rows]
    return CompanyMatchFeed(items=items, total=total, min_score=floor)


async def _set_status(
    session: AsyncSession, user_id: uuid.UUID, match_id: uuid.UUID, action: str
) -> CompanyMatchOut:
    match, company, target = await _owned_match(session, user_id, match_id)
    to, allowed_from = _ACTIONS[action]
    if match.status != to:
        if match.status not in allowed_from:
            raise api_error(
                status.HTTP_409_CONFLICT,
                "match_locked",
                f"Can't {action} a company that is {match.status.value}.",
            )
        match.status = to
        await session.commit()
    return await _match_out(session, match, company, target)


@router.post("/matches/{match_id}/queue", response_model=CompanyMatchOut)
async def queue_match(match_id: uuid.UUID, user: CurrentUser, session: Session) -> CompanyMatchOut:
    """Put this company first in line for the next daily batch."""
    return await _set_status(session, user.id, match_id, "queue")


@router.post("/matches/{match_id}/hide", response_model=CompanyMatchOut)
async def hide_match(match_id: uuid.UUID, user: CurrentUser, session: Session) -> CompanyMatchOut:
    return await _set_status(session, user.id, match_id, "hide")


@router.post("/matches/{match_id}/restore", response_model=CompanyMatchOut)
async def restore_match(match_id: uuid.UUID, user: CurrentUser, session: Session) -> CompanyMatchOut:
    return await _set_status(session, user.id, match_id, "restore")


@router.post("/matches/{match_id}/draft", response_model=OutreachDetail)
async def draft_now(
    match_id: uuid.UUID,
    user: CurrentUser,
    session: Session,
    llm: Annotated[LLMClient, Depends(get_llm_client)],
    factory: Annotated[ProviderFactory, Depends(get_contact_provider_factory)],
) -> OutreachDetail:
    """Run contact → tailor → draft for this company now. A draft that already exists is returned as
    is; a failed one is retried."""
    match, company, _ = await _owned_match(session, user.id, match_id)
    company_name = company.name
    if match.status == CompanyMatchStatus.HIDDEN:
        raise api_error(status.HTTP_409_CONFLICT, "match_locked", "Restore this company first.")
    try:
        outreach = await start_open_outreach(session, user.id, match)
    except OutreachConflictError as exc:
        await session.rollback()
        raise api_error(
            status.HTTP_409_CONFLICT,
            "outreach_exists",
            f"You already have an outreach in progress at {company_name}; one at a time per company.",
        ) from exc
    if outreach.status == OutreachStatus.DRAFTING:
        await run_pipeline(session, outreach, user.id, llm, factory)
    else:
        await session.commit()
    return await outreach_detail(session, outreach)
