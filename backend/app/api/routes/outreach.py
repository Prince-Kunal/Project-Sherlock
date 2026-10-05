"""Outreach (PLAN.md Phases 5-6). Phase 5: view an outreach and set or swap its contact."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import api_error
from app.core.auth import CurrentUser
from app.core.db import get_session
from app.models import Outreach
from app.schemas.outreach import ManualContactIn, OutreachOut
from app.services.contacts.service import ManualContactError, ProviderFactory, set_contact_manually
from app.services.contacts.views import outreach_out
from app.services.registry import get_contact_provider_factory

router = APIRouter(prefix="/outreach", tags=["outreach"])

Session = Annotated[AsyncSession, Depends(get_session)]
Factory = Annotated[ProviderFactory, Depends(get_contact_provider_factory)]

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


@router.get("/{outreach_id}", response_model=OutreachOut)
async def get_outreach(outreach_id: uuid.UUID, user: CurrentUser, session: Session) -> OutreachOut:
    return await outreach_out(session, await _owned(session, user.id, outreach_id))


@router.post("/{outreach_id}/contact", response_model=OutreachOut)
async def set_contact(
    outreach_id: uuid.UUID, body: ManualContactIn, user: CurrentUser, session: Session, factory: Factory
) -> OutreachOut:
    """Set or swap the contact by hand. The address is verified first; only valid or accept-all
    addresses are accepted. A `no_contact` failure goes back to drafting."""
    outreach = await _owned(session, user.id, outreach_id)
    try:
        await set_contact_manually(
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
    await session.commit()
    return await outreach_out(session, outreach)
