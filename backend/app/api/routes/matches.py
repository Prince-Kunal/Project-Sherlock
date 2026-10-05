"""The user's scored jobs (PLAN.md Phase 3). Every query is scoped to the current user (invariant 5)."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import api_error
from app.core.auth import CurrentUser
from app.core.config import get_settings
from app.core.db import get_session
from app.models import Company, Job, JobMatch
from app.models.enums import JobMatchStatus
from app.schemas.jobs import JobOut
from app.schemas.matches import MatchFeed, MatchOut, MatchStatusFilter, ScoringStatus
from app.services.llm.user_keys import get_key_row
from app.services.matching.filters import hard_filter_conditions
from app.services.matching.pipeline import OPERATION, daily_window_start, load_preferences
from app.services.usage import llm_calls_since
from app.workers.queue import enqueue

router = APIRouter(prefix="/matches", tags=["matches"])

Session = Annotated[AsyncSession, Depends(get_session)]

_ACTIVE = (JobMatchStatus.NEW, JobMatchStatus.SHORTLISTED)
# Where each action may move a match from. In-pipeline and expired matches are not user-editable.
_ACTIONS: dict[str, tuple[JobMatchStatus, tuple[JobMatchStatus, ...]]] = {
    "shortlist": (JobMatchStatus.SHORTLISTED, (JobMatchStatus.NEW, JobMatchStatus.HIDDEN)),
    "hide": (JobMatchStatus.HIDDEN, (JobMatchStatus.NEW, JobMatchStatus.SHORTLISTED)),
    "restore": (JobMatchStatus.NEW, (JobMatchStatus.SHORTLISTED, JobMatchStatus.HIDDEN)),
}


def _out(match: JobMatch, job: Job, company: Company, now: datetime) -> MatchOut:
    return MatchOut(
        id=match.id,
        job=JobOut.from_row(job, company, now),
        fit_score=match.llm_score,
        embedding_score=match.embedding_score,
        matched_skills=match.matched_skills,
        missing_skills=match.missing_skills,
        reasoning=match.reasoning,
        status=match.status,
        created_at=match.created_at,
    )


@router.get("", response_model=MatchFeed)
async def list_matches(
    user: CurrentUser,
    session: Session,
    match_status: Annotated[MatchStatusFilter, Query(alias="status")] = "active",
    min_score: Annotated[int | None, Query(ge=0, le=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MatchFeed:
    """Scored jobs, best first. Defaults: new + shortlisted, fit score ≥ the user's min_fit_score.
    The user's current preferences (age, type, stage, blocked companies) apply at read time too."""
    prefs = await load_preferences(session, user.id)
    score_floor = prefs.min_fit_score if min_score is None else min_score
    now = datetime.now(UTC)

    conditions = [
        JobMatch.user_id == user.id,
        JobMatch.llm_score >= score_floor,
        *hard_filter_conditions(
            user.id,
            max_job_age_days=prefs.max_job_age_days,
            employment_types=list(prefs.employment_types),
            company_stages=list(prefs.company_stages),
            now=now,
        ),
    ]
    if match_status == "active":
        conditions.append(JobMatch.status.in_(_ACTIVE))
    elif match_status not in ("in_pipeline", "expired"):
        conditions.append(JobMatch.status == JobMatchStatus(match_status))
    else:
        # These are kept for history: show them even when the job has since closed or aged out.
        conditions = [
            JobMatch.user_id == user.id,
            JobMatch.status == JobMatchStatus(match_status),
            or_(JobMatch.llm_score.is_(None), JobMatch.llm_score >= score_floor),
        ]

    base = (
        select(JobMatch, Job, Company)
        .join(Job, Job.id == JobMatch.job_id)
        .join(Company, Company.id == Job.company_id)
        .where(*conditions)
    )
    total = await session.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = (
        await session.execute(
            base.order_by(
                JobMatch.llm_score.desc().nulls_last(),
                JobMatch.embedding_score.desc().nulls_last(),
                JobMatch.id,
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()

    calls = await llm_calls_since(session, user.id, OPERATION, daily_window_start(now))
    key = await get_key_row(session, user.id)
    return MatchFeed(
        items=[_out(m, j, c, now) for m, j, c in rows],
        total=total,
        min_score=score_floor,
        scoring=ScoringStatus(
            llm_key_configured=key is not None or get_settings().allow_owner_key_fallback,
            calls_last_24h=calls,
            daily_limit=get_settings().match_daily_llm_calls,
        ),
    )


class RefreshQueued(BaseModel):
    queued: bool


@router.post("/refresh", response_model=RefreshQueued, status_code=status.HTTP_202_ACCEPTED)
async def refresh_matches(user: CurrentUser) -> RefreshQueued:
    """Score new jobs for this user now instead of waiting for the next poll."""
    job_id = await enqueue("match_jobs_for_users", str(user.id), job_id=f"match_jobs:{user.id}")
    return RefreshQueued(queued=job_id is not None)


async def _set_status(
    session: AsyncSession, user_id: uuid.UUID, match_id: uuid.UUID, action: str
) -> MatchOut:
    row = (
        await session.execute(
            select(JobMatch, Job, Company)
            .join(Job, Job.id == JobMatch.job_id)
            .join(Company, Company.id == Job.company_id)
            .where(JobMatch.id == match_id, JobMatch.user_id == user_id)
        )
    ).first()
    if row is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "match_not_found", "Match not found.")
    match, job, company = row
    target, allowed_from = _ACTIONS[action]
    if match.status != target:
        if match.status not in allowed_from:
            raise api_error(
                status.HTTP_409_CONFLICT,
                "match_locked",
                f"A match that is {match.status.value.replace('_', ' ')} can't be changed here.",
            )
        match.status = target
        await session.commit()
        await session.refresh(match)
    return _out(match, job, company, datetime.now(UTC))


@router.post("/{match_id}/shortlist", response_model=MatchOut)
async def shortlist(match_id: uuid.UUID, user: CurrentUser, session: Session) -> MatchOut:
    return await _set_status(session, user.id, match_id, "shortlist")


@router.post("/{match_id}/hide", response_model=MatchOut)
async def hide(match_id: uuid.UUID, user: CurrentUser, session: Session) -> MatchOut:
    return await _set_status(session, user.id, match_id, "hide")


@router.post("/{match_id}/restore", response_model=MatchOut)
async def restore(match_id: uuid.UUID, user: CurrentUser, session: Session) -> MatchOut:
    """Undo shortlist/hide: back to new."""
    return await _set_status(session, user.id, match_id, "restore")
