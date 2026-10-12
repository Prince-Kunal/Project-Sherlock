"""Outreach rows as API responses (shared by the matches and outreach routes)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, Contact, Job, JobMatch, Outreach, OutreachEvent
from app.models.enums import OutreachEventType, OutreachStatus
from app.schemas.jobs import CompanyBrief, JobOut
from app.schemas.outreach import ContactOut, OutreachDetail, OutreachListItem, OutreachOut, TimelineEntry
from app.schemas.resume import MasterResume
from app.schemas.tailor import ResumeChange
from app.services.email.style import style_issues
from app.services.resume.ats_check import AtsReport, KeywordCoverage


async def outreach_out(session: AsyncSession, outreach: Outreach) -> OutreachOut:
    company = await session.get(Company, outreach.company_id)
    contact = await session.get(Contact, outreach.contact_id) if outreach.contact_id else None
    message = None
    if outreach.status == OutreachStatus.FAILED:
        event = await session.scalar(
            select(OutreachEvent)
            .where(OutreachEvent.outreach_id == outreach.id, OutreachEvent.type == OutreachEventType.FAILED)
            .order_by(OutreachEvent.created_at.desc())
            .limit(1)
        )
        message = event.payload.get("message") if event else None
    return OutreachOut(
        id=outreach.id,
        status=outreach.status,
        campaign_type=outreach.campaign_type,
        job_id=outreach.job_id,
        company=CompanyBrief.model_validate(company),
        contact=ContactOut.model_validate(contact) if contact else None,
        failure_reason=outreach.failure_reason,
        failure_message=message,
        created_at=outreach.created_at,
    )


async def latest_outreach_by_job(
    session: AsyncSession, user_id: uuid.UUID, job_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Outreach]:
    rows = (
        await session.scalars(
            select(Outreach)
            .where(Outreach.user_id == user_id, Outreach.job_id.in_(job_ids))
            .order_by(Outreach.created_at)
        )
    ).all()
    return {row.job_id: row for row in rows if row.job_id is not None}  # later rows win


async def outreach_list_item(session: AsyncSession, outreach: Outreach) -> OutreachListItem:
    if "updated_at" in inspect(outreach).unloaded:  # server-side onupdate value, expired by the flush
        await session.refresh(outreach, ["updated_at"])
    base = await outreach_out(session, outreach)
    job = await session.get(Job, outreach.job_id) if outreach.job_id else None
    match = await _match_for(session, outreach)
    return OutreachListItem(
        **base.model_dump(),
        subject=outreach.subject,
        job_title=job.title if job else None,
        fit_score=match.llm_score if match else None,
        updated_at=outreach.updated_at,
        scheduled_at=outreach.scheduled_at,
        sent_at=outreach.sent_at,
        replied_at=outreach.replied_at,
        outcome=outreach.outcome,
        notes=outreach.notes,
        is_followup=outreach.followup_count > 0,
        send_error=await _send_error(session, outreach),
    )


async def _send_error(session: AsyncSession, outreach: Outreach) -> str | None:
    """The reason the last send came back to review, while it's waiting for a new approval."""
    if outreach.status != OutreachStatus.PENDING_REVIEW:
        return None
    event = await session.scalar(
        select(OutreachEvent)
        .where(OutreachEvent.outreach_id == outreach.id)
        .order_by(OutreachEvent.created_at.desc())
        .limit(1)
    )
    if event is None or event.type != OutreachEventType.SEND_FAILED:
        return None
    first = await session.scalar(
        select(OutreachEvent)
        .where(OutreachEvent.outreach_id == outreach.id, OutreachEvent.type == OutreachEventType.SEND_FAILED)
        .order_by(OutreachEvent.created_at.desc())
        .offset(1)
        .limit(1)
    )
    payload = (first or event).payload
    return str(payload.get("message") or payload.get("reason") or "The send failed.")


async def _match_for(session: AsyncSession, outreach: Outreach) -> JobMatch | None:
    if outreach.job_id is None:
        return None
    return await session.scalar(
        select(JobMatch).where(JobMatch.user_id == outreach.user_id, JobMatch.job_id == outreach.job_id)
    )


async def outreach_detail(session: AsyncSession, outreach: Outreach) -> OutreachDetail:
    item = await outreach_list_item(session, outreach)
    company = await session.get(Company, outreach.company_id)
    job = await session.get(Job, outreach.job_id) if outreach.job_id else None
    match = await _match_for(session, outreach)
    record = outreach.tailored_resume or {}
    approved = await session.scalar(
        select(OutreachEvent.created_at)
        .where(OutreachEvent.outreach_id == outreach.id, OutreachEvent.type == OutreachEventType.APPROVED)
        .order_by(OutreachEvent.created_at.desc())
        .limit(1)
    )
    return OutreachDetail(
        **item.model_dump(),
        body=outreach.body,
        personalization_source=outreach.personalization_source,
        match_id=match.id if match else None,
        job=JobOut.from_row(job, company, datetime.now(UTC)) if job and company else None,
        matched_skills=match.matched_skills if match else [],
        missing_skills=match.missing_skills if match else [],
        resume_pdf_url=f"/outreach/{outreach.id}/resume.pdf" if outreach.resume_pdf_path else None,
        resume_filename=record.get("filename"),
        resume_diff=[ResumeChange.model_validate(c) for c in outreach.resume_diff or []],
        keyword_coverage=(
            KeywordCoverage.model_validate(outreach.ats_keyword_coverage)
            if outreach.ats_keyword_coverage
            else None
        ),
        ats=AtsReport.model_validate(record["ats"]) if record.get("ats") else None,
        approved_at=approved,
        style_warnings=_style_warnings(outreach, job),
    )


def _style_warnings(outreach: Outreach, job: Job | None) -> list[str]:
    if not outreach.body:
        return []
    bullets: list[str] = []
    if (record := outreach.tailored_resume) and (resume := record.get("resume")):
        bullets = [b.text for b in MasterResume.model_validate(resume).all_bullets()]
    sources = [job.description_text if job else "", *bullets]
    return [i.message for i in style_issues(outreach.subject or "", outreach.body, sources)]


_TITLES = {
    OutreachEventType.DRAFTED: "Draft written",
    OutreachEventType.EDITED: "You edited the draft",
    OutreachEventType.REGENERATED: "Draft rewritten",
    OutreachEventType.APPROVED: "You approved it",
    OutreachEventType.SKIPPED: "Skipped",
    OutreachEventType.SCHEDULED: "Scheduled",
    OutreachEventType.SENT: "Sent",
    OutreachEventType.SEND_FAILED: "Send failed",
    OutreachEventType.REPLY_DETECTED: "Reply received",
    OutreachEventType.FOLLOWUP_DUE: "Follow-up due",
    OutreachEventType.FOLLOWUP_DRAFTED: "Follow-up drafted",
    OutreachEventType.FOLLOWUP_SENT: "Follow-up sent",
    OutreachEventType.BOUNCED: "Bounced",
    OutreachEventType.CLOSED: "Closed",
    OutreachEventType.OUTCOME_SET: "Outcome set",
    OutreachEventType.FAILED: "Drafting failed",
    OutreachEventType.RETRIED: "Retried",
    OutreachEventType.CONTACT_CHANGED: "Contact set",
}


async def outreach_timeline(session: AsyncSession, outreach: Outreach) -> list[TimelineEntry]:
    events = (
        await session.scalars(
            select(OutreachEvent)
            .where(OutreachEvent.outreach_id == outreach.id)
            .order_by(OutreachEvent.created_at)
        )
    ).all()
    entries = []
    for event in events:
        payload = event.payload or {}
        if event.type == OutreachEventType.SEND_FAILED and payload.get("returned_to_review"):
            continue  # the second half of one failure
        text = None
        if event.type in (OutreachEventType.SENT, OutreachEventType.FOLLOWUP_SENT):
            text = payload.get("body")
        elif event.type in (OutreachEventType.REPLY_DETECTED, OutreachEventType.BOUNCED):
            text = payload.get("text") or payload.get("snippet")
        entries.append(
            TimelineEntry(
                at=event.created_at,
                type=event.type,
                status=OutreachStatus(payload["to"])
                if payload.get("to") in OutreachStatus._value2member_map_
                else None,
                title=_TITLES.get(event.type, event.type.value.replace("_", " ").capitalize()),
                text=text,
                reason=payload.get("reason") or payload.get("message"),
            )
        )
    return entries
