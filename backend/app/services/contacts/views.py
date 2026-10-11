"""Outreach rows as API responses (shared by the matches and outreach routes)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, Contact, Job, JobMatch, Outreach, OutreachEvent
from app.models.enums import OutreachEventType, OutreachStatus
from app.schemas.jobs import CompanyBrief, JobOut
from app.schemas.outreach import ContactOut, OutreachDetail, OutreachListItem, OutreachOut
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
    )


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
