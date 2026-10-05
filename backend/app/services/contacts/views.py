"""Outreach rows as API responses (shared by the matches and outreach routes)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, Contact, Outreach, OutreachEvent
from app.models.enums import OutreachEventType, OutreachStatus
from app.schemas.jobs import CompanyBrief
from app.schemas.outreach import ContactOut, OutreachOut


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
