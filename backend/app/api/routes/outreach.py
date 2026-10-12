"""Outreach (PLAN.md Phases 5-6): the review queue (list, view, edit, regenerate, approve, skip), the
tailored resume PDF, and setting or swapping the contact. Every query is scoped to the current user
(invariant 5); status only changes through services/email/state.py."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import api_error, llm_errors
from app.core.auth import CurrentUser
from app.core.db import get_session
from app.models import Job, JobMatch, Outreach
from app.models.enums import JobMatchStatus, Outcome, OutreachEventType, OutreachStatus
from app.schemas.outreach import (
    BuildQueued,
    DraftEditIn,
    ManualContactIn,
    OutreachDetail,
    OutreachList,
    RegenerateIn,
    ReviewStats,
    TimelineEntry,
    TrackingIn,
)
from app.services.contacts.service import ManualContactError, ProviderFactory, set_contact_manually
from app.services.contacts.views import outreach_detail, outreach_list_item, outreach_timeline
from app.services.email.drafter import MAX_EDIT_WORDS, DraftError, check_text, replace_greeting
from app.services.email.pipeline import DraftingPausedError, DraftPipeline, pdf_for
from app.services.email.state import InvalidTransitionError, record_event, transition
from app.services.llm.client import LLMClient
from app.services.llm.user_keys import resolve_api_key
from app.services.matching.filters import hard_filter_conditions
from app.services.matching.pipeline import load_preferences
from app.services.registry import get_contact_provider_factory, get_llm_client
from app.workers.queue import enqueue

router = APIRouter(prefix="/outreach", tags=["outreach"])

Session = Annotated[AsyncSession, Depends(get_session)]
Factory = Annotated[ProviderFactory, Depends(get_contact_provider_factory)]
LLM = Annotated[LLMClient, Depends(get_llm_client)]

_ERROR_STATUS = {
    "outreach_locked": status.HTTP_409_CONFLICT,
    "contact_cooldown": status.HTTP_409_CONFLICT,
    "hunter_key_required": status.HTTP_428_PRECONDITION_REQUIRED,
    "contact_quota": status.HTTP_429_TOO_MANY_REQUESTS,
    "contact_key_invalid": status.HTTP_400_BAD_REQUEST,
}


async def _owned(session: AsyncSession, user_id: uuid.UUID, outreach_id: uuid.UUID) -> Outreach:
    outreach = await session.scalar(
        select(Outreach).where(Outreach.id == outreach_id, Outreach.user_id == user_id)
    )
    if outreach is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "outreach_not_found", "Outreach not found.")
    return outreach


def _in_review(outreach: Outreach) -> None:
    if outreach.status != OutreachStatus.PENDING_REVIEW:
        raise api_error(
            status.HTTP_409_CONFLICT,
            "draft_locked",
            "Only drafts waiting for review can be changed "
            f"(this one is {outreach.status.value.replace('_', ' ')}).",
        )


@router.get("", response_model=OutreachList)
async def list_outreach(
    user: CurrentUser,
    session: Session,
    outreach_status: Annotated[list[OutreachStatus] | None, Query(alias="status")] = None,
    outcome: Annotated[list[Outcome] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OutreachList:
    """The user's outreach, oldest draft first for the review queue (`?status=pending_review`),
    otherwise most recently changed first."""
    conditions = [Outreach.user_id == user.id]
    if outreach_status:
        conditions.append(Outreach.status.in_(outreach_status))
    if outcome:
        conditions.append(Outreach.outcome.in_(outcome))
    order = (
        Outreach.created_at
        if outreach_status == [OutreachStatus.PENDING_REVIEW]
        else Outreach.updated_at.desc()
    )
    total = await session.scalar(select(func.count()).select_from(Outreach).where(*conditions)) or 0
    rows = (
        await session.scalars(
            select(Outreach).where(*conditions).order_by(order, Outreach.id).limit(limit).offset(offset)
        )
    ).all()
    return OutreachList(items=[await outreach_list_item(session, o) for o in rows], total=total)


@router.get("/stats", response_model=ReviewStats)
async def review_stats(user: CurrentUser, session: Session) -> ReviewStats:
    """The stat cards on the review queue."""
    prefs = await load_preferences(session, user.id)
    now = datetime.now(UTC)
    local = now.astimezone(ZoneInfo(prefs.timezone))
    week_start = (local - timedelta(days=local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)

    async def count(*conditions: ColumnElement[bool]) -> int:
        query = select(func.count()).select_from(Outreach).where(Outreach.user_id == user.id, *conditions)
        return int(await session.scalar(query) or 0)

    new_matches = await session.scalar(
        select(func.count())
        .select_from(JobMatch)
        .join(Job, Job.id == JobMatch.job_id)
        .where(
            JobMatch.user_id == user.id,
            JobMatch.status == JobMatchStatus.NEW,
            JobMatch.llm_score >= prefs.min_fit_score,
            *hard_filter_conditions(
                user.id,
                max_job_age_days=prefs.max_job_age_days,
                employment_types=list(prefs.employment_types),
                company_stages=list(prefs.company_stages),
                now=now,
            ),
        )
    )
    return ReviewStats(
        pending_review=await count(Outreach.status == OutreachStatus.PENDING_REVIEW),
        new_matches=int(new_matches or 0),
        sent_this_week=await count(Outreach.sent_at >= week_start),
        daily_send_cap=prefs.daily_send_cap,
        replies=await count(Outreach.replied_at.is_not(None)),
        followups_due=await count(Outreach.status == OutreachStatus.FOLLOWUP_DUE),
        failed=await count(Outreach.status == OutreachStatus.FAILED),
    )


@router.post("/build", response_model=BuildQueued, status_code=status.HTTP_202_ACCEPTED)
async def build_now(user: CurrentUser) -> BuildQueued:
    """Run today's draft batch now instead of waiting for 07:00."""
    job_id = await enqueue("build_daily_drafts", str(user.id), job_id=f"build_drafts:{user.id}")
    return BuildQueued(queued=job_id is not None)


@router.get("/{outreach_id}", response_model=OutreachDetail)
async def get_outreach(outreach_id: uuid.UUID, user: CurrentUser, session: Session) -> OutreachDetail:
    return await outreach_detail(session, await _owned(session, user.id, outreach_id))


@router.patch("/{outreach_id}", response_model=OutreachDetail)
async def edit_draft(
    outreach_id: uuid.UUID, body: DraftEditIn, user: CurrentUser, session: Session
) -> OutreachDetail:
    """Edit the subject and/or body. The opt-out line must stay (invariant 9); the text before the
    edit is kept in the `edited` event."""
    outreach = await _owned(session, user.id, outreach_id)
    _in_review(outreach)
    subject = body.subject.strip() if body.subject is not None else outreach.subject or ""
    text = body.body.strip() if body.body is not None else outreach.body or ""
    if (subject, text) != (outreach.subject, outreach.body):
        issues = check_text(subject, text, max_words=MAX_EDIT_WORDS)
        if issues:
            raise api_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "draft_invalid", " ".join(i.message for i in issues)
            )
        await record_event(
            session,
            outreach,
            OutreachEventType.EDITED,
            {
                "before": {"subject": outreach.subject, "body": outreach.body},
                "after": {"subject": subject, "body": text},
                "actor": str(user.id),
            },
        )
        outreach.subject, outreach.body = subject, text
        await session.commit()
    return await outreach_detail(session, outreach)


@router.post("/{outreach_id}/regenerate", response_model=OutreachDetail)
async def regenerate(
    outreach_id: uuid.UUID,
    body: RegenerateIn,
    user: CurrentUser,
    session: Session,
    llm: LLM,
    factory: Factory,
) -> OutreachDetail:
    """A fresh email (one smart-model request, two if the first is rejected), optionally steered by a
    hint. The tailored resume stays as it is."""
    outreach = await _owned(session, user.id, outreach_id)
    _in_review(outreach)
    with llm_errors():
        api_key = await resolve_api_key(session, user.id)
        try:
            subject, text, source = await DraftPipeline(llm, factory).regenerate(
                session, outreach, hint=body.hint, api_key=api_key
            )
        except DraftError as exc:
            raise api_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                exc.reason,
                "Couldn't write a valid email: " + ("; ".join(i.message for i in exc.issues) or str(exc)),
            ) from exc
        finally:
            await session.commit()  # keep the usage row, also when drafting failed
    await transition(
        session,
        outreach,
        OutreachStatus.PENDING_REVIEW,
        actor_id=user.id,
        event=OutreachEventType.REGENERATED,
        payload={"before": {"subject": outreach.subject, "body": outreach.body}, "hint": body.hint},
    )
    outreach.subject, outreach.body, outreach.personalization_source = subject, text, source
    await session.commit()
    return await outreach_detail(session, outreach)


@router.post("/{outreach_id}/approve", response_model=OutreachDetail)
async def approve(outreach_id: uuid.UUID, user: CurrentUser, session: Session) -> OutreachDetail:
    """Approve the draft for sending (invariant 1: the sender checks this `approved` event again at
    send time)."""
    outreach = await _owned(session, user.id, outreach_id)
    _in_review(outreach)
    problems = check_text(outreach.subject or "", outreach.body or "", max_words=MAX_EDIT_WORDS)
    if problems:
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "draft_invalid", " ".join(i.message for i in problems)
        )
    if outreach.contact_id is None:
        raise api_error(status.HTTP_409_CONFLICT, "no_contact", "Add a contact before approving.")
    ats = (outreach.tailored_resume or {}).get("ats") or {}
    if pdf_for(outreach) is None or not ats.get("passed"):  # invariant 11
        raise api_error(
            status.HTTP_409_CONFLICT,
            "resume_missing",
            "The tailored resume is missing or failed the ATS check.",
        )
    await transition(session, outreach, OutreachStatus.APPROVED, actor_id=user.id)
    await session.commit()
    return await outreach_detail(session, outreach)


@router.post("/{outreach_id}/skip", response_model=OutreachDetail)
async def skip(outreach_id: uuid.UUID, user: CurrentUser, session: Session) -> OutreachDetail:
    outreach = await _owned(session, user.id, outreach_id)
    _in_review(outreach)
    await transition(session, outreach, OutreachStatus.SKIPPED, actor_id=user.id)
    await session.commit()
    return await outreach_detail(session, outreach)


@router.post("/{outreach_id}/retry", response_model=OutreachDetail)
async def retry(
    outreach_id: uuid.UUID, user: CurrentUser, session: Session, llm: LLM, factory: Factory
) -> OutreachDetail:
    """Run the pipeline again for a failed (or interrupted) outreach: contact → tailor → draft."""
    outreach = await _owned(session, user.id, outreach_id)
    try:
        if outreach.status == OutreachStatus.FAILED:
            await transition(session, outreach, OutreachStatus.DRAFTING, actor_id=user.id)
    except InvalidTransitionError as exc:
        raise api_error(status.HTTP_409_CONFLICT, "draft_locked", str(exc)) from exc
    if outreach.status != OutreachStatus.DRAFTING:
        raise api_error(status.HTTP_409_CONFLICT, "draft_locked", "Only failed drafts can be retried.")
    await run_pipeline(session, outreach, user.id, llm, factory)
    return await outreach_detail(session, outreach)


async def run_pipeline(
    session: AsyncSession, outreach: Outreach, user_id: uuid.UUID, llm: LLMClient, factory: ProviderFactory
) -> None:
    """Shared by "Retry" and the match's "Draft now". Commits; LLM key/quota problems become API errors
    and leave the outreach in drafting."""
    try:
        with llm_errors():
            try:
                await DraftPipeline(llm, factory).run(session, outreach, actor_id=user_id)
            except DraftingPausedError as exc:
                raise exc.cause from exc
    finally:
        await session.commit()  # the contact found and the usage rows are kept either way


@router.post("/{outreach_id}/unapprove", response_model=OutreachDetail)
async def unapprove(outreach_id: uuid.UUID, user: CurrentUser, session: Session) -> OutreachDetail:
    """Pull an approved or scheduled email back to review before it goes out."""
    outreach = await _owned(session, user.id, outreach_id)
    if outreach.status not in (OutreachStatus.APPROVED, OutreachStatus.SCHEDULED):
        raise api_error(
            status.HTTP_409_CONFLICT, "not_approved", "Only approved emails that haven't gone out yet."
        )
    outreach.scheduled_at = None
    await transition(
        session, outreach, OutreachStatus.PENDING_REVIEW, actor_id=user.id, event=OutreachEventType.EDITED,
        payload={"unapproved": True},
    )  # fmt: skip
    await session.commit()
    return await outreach_detail(session, outreach)


@router.patch("/{outreach_id}/tracking", response_model=OutreachDetail)
async def set_tracking(
    outreach_id: uuid.UUID, body: TrackingIn, user: CurrentUser, session: Session
) -> OutreachDetail:
    """Outcome (referred, interview, …) and private notes, for any outreach."""
    outreach = await _owned(session, user.id, outreach_id)
    if body.outcome is not None and body.outcome != outreach.outcome:
        await record_event(
            session,
            outreach,
            OutreachEventType.OUTCOME_SET,
            {"before": outreach.outcome.value, "outcome": body.outcome.value, "actor": str(user.id)},
        )
        outreach.outcome = body.outcome
    if body.notes is not None:
        outreach.notes = body.notes
    await session.commit()
    return await outreach_detail(session, outreach)


@router.post("/{outreach_id}/close", response_model=OutreachDetail)
async def close(outreach_id: uuid.UUID, user: CurrentUser, session: Session) -> OutreachDetail:
    """Close a sent or replied outreach by hand (e.g. no follow-up wanted)."""
    outreach = await _owned(session, user.id, outreach_id)
    try:
        await transition(
            session, outreach, OutreachStatus.CLOSED, actor_id=user.id, payload={"reason": "manual"}
        )
    except InvalidTransitionError as exc:
        raise api_error(status.HTTP_409_CONFLICT, "cannot_close", str(exc)) from exc
    await session.commit()
    return await outreach_detail(session, outreach)


@router.get("/{outreach_id}/timeline", response_model=list[TimelineEntry])
async def timeline(outreach_id: uuid.UUID, user: CurrentUser, session: Session) -> list[TimelineEntry]:
    return await outreach_timeline(session, await _owned(session, user.id, outreach_id))


@router.get("/{outreach_id}/resume.pdf", response_class=FileResponse)
async def resume_pdf(outreach_id: uuid.UUID, user: CurrentUser, session: Session) -> FileResponse:
    outreach = await _owned(session, user.id, outreach_id)
    path = pdf_for(outreach)
    if path is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "no_resume_pdf", "This draft has no tailored resume yet.")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=path.name,
        content_disposition_type="inline",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/{outreach_id}/contact", response_model=OutreachDetail)
async def set_contact(
    outreach_id: uuid.UUID, body: ManualContactIn, user: CurrentUser, session: Session, factory: Factory
) -> OutreachDetail:
    """Set or swap the contact by hand. The address is verified first; only valid or accept-all
    addresses are accepted. A `no_contact` failure goes back to drafting; a draft in review greets
    the new person."""
    outreach = await _owned(session, user.id, outreach_id)
    try:
        contact = await set_contact_manually(
            session,
            outreach,
            email=str(body.email),
            full_name=body.full_name,
            title=body.title,
            factory=factory,
            actor_id=user.id,
        )
    except ManualContactError as exc:
        code = _ERROR_STATUS.get(exc.code, status.HTTP_422_UNPROCESSABLE_CONTENT)
        raise api_error(code, exc.code, str(exc)) from exc
    if outreach.status == OutreachStatus.PENDING_REVIEW and outreach.body:
        outreach.body = replace_greeting(outreach.body, contact)
    await session.commit()
    return await outreach_detail(session, outreach)
