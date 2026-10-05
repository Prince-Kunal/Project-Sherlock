"""The user's scored jobs (PLAN.md Phase 3). Every query is scoped to the current user (invariant 5)."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import api_error, llm_errors
from app.core.auth import CurrentUser
from app.core.config import get_settings
from app.core.db import get_session
from app.models import Company, Job, JobMatch
from app.models.enums import JobMatchStatus
from app.schemas.jobs import JobOut
from app.schemas.matches import MatchFeed, MatchOut, MatchStatusFilter, ScoringStatus
from app.schemas.resume import MasterResume
from app.schemas.tailor import TailorPreviewOut
from app.services.llm.client import LLMClient
from app.services.llm.user_keys import get_key_row, resolve_api_key
from app.services.matching.filters import hard_filter_conditions
from app.services.matching.pipeline import OPERATION, daily_window_start, load_preferences
from app.services.registry import get_llm_client
from app.services.resume import store
from app.services.resume.files import find_pdf, preview_folder, save_tailored_pdf
from app.services.resume.tailor import Tailor, TailorError
from app.services.usage import llm_calls_since, logged_llm_usage
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


async def _owned(
    session: AsyncSession, user_id: uuid.UUID, match_id: uuid.UUID
) -> tuple[JobMatch, Job, Company]:
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
    return match, job, company


async def _set_status(
    session: AsyncSession, user_id: uuid.UUID, match_id: uuid.UUID, action: str
) -> MatchOut:
    match, job, company = await _owned(session, user_id, match_id)
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


# --- Tailored resume preview (PLAN.md Phase 4; the full draft pipeline arrives in Phase 6) ---------


@router.post("/{match_id}/tailor-preview", response_model=TailorPreviewOut)
async def tailor_preview(
    match_id: uuid.UUID,
    user: CurrentUser,
    session: Session,
    llm: Annotated[LLMClient, Depends(get_llm_client)],
) -> TailorPreviewOut:
    """Tailor the current resume to this match's job: one smart-model request (two if the first plan
    is rejected by the validator), then a 1-page, ATS-checked PDF."""
    match, job, company = await _owned(session, user.id, match_id)
    resume_row = await store.get_current(session, user.id)
    if resume_row is None:
        raise api_error(status.HTTP_409_CONFLICT, "no_resume", "Upload your resume first.")
    master = MasterResume.model_validate(resume_row.data)

    with llm_errors():
        api_key = await resolve_api_key(session, user.id)
        try:
            async with logged_llm_usage(session, user.id, "tailor_resume"):
                result = await Tailor(llm).tailor(master, job, company, api_key)
        except TailorError as exc:
            details = "; ".join(i.message for i in exc.issues[:3]) or str(exc)
            raise api_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"tailor_{exc.reason}",
                f"Couldn't tailor the resume for this job ({exc.reason.replace('_', ' ')}): {details}",
            ) from exc

    await save_tailored_pdf(user.id, preview_folder(match.id), result.filename, result.rendered.pdf)
    return TailorPreviewOut(
        match_id=str(match.id),
        pdf_url=f"/matches/{match.id}/tailored.pdf",
        filename=result.filename,
        section_order=result.section_order,
        diff=result.diff,
        keyword_coverage=result.keyword_coverage,
        ats=result.ats,
        bullets_dropped_to_fit=len(result.dropped_to_fit),
    )


@router.get("/{match_id}/tailored.pdf", response_class=FileResponse)
async def tailored_pdf(match_id: uuid.UUID, user: CurrentUser, session: Session) -> FileResponse:
    match, _, _ = await _owned(session, user.id, match_id)
    path = find_pdf(user.id, preview_folder(match.id))
    if path is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "no_preview", "Generate a preview first.")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=path.name,
        content_disposition_type="inline",
        headers={"Cache-Control": "no-store"},
    )
