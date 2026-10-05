import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import api_error, llm_errors
from app.core.auth import CurrentUser
from app.core.config import get_settings
from app.core.db import get_session
from app.models.enums import ServiceKeyType
from app.schemas.settings import HunterKeyIn, HunterKeyStatus, LLMKeyIn, LLMKeyStatus
from app.services.contacts.base import ContactProviderAuthError, ContactProviderError
from app.services.contacts.keys import get_service_key_row, save_service_key
from app.services.contacts.service import ProviderFactory, contact_searches_this_month
from app.services.llm.client import LLMClient
from app.services.llm.user_keys import FREE_TIER_NOTICE, get_key_row, save_key
from app.services.registry import get_contact_provider_factory, get_llm_client

router = APIRouter(prefix="/settings", tags=["settings"])

Session = Annotated[AsyncSession, Depends(get_session)]


async def _status(session: AsyncSession, user_id: uuid.UUID) -> LLMKeyStatus:
    row = await get_key_row(session, user_id)
    return LLMKeyStatus(
        configured=row is not None,
        provider=row.provider.value if row else None,
        verified_at=row.verified_at if row else None,
        owner_fallback_allowed=get_settings().allow_owner_key_fallback,
        notice=FREE_TIER_NOTICE,
    )


@router.get("/llm-key", response_model=LLMKeyStatus)
async def get_llm_key(user: CurrentUser, session: Session) -> LLMKeyStatus:
    """Key status only. The key itself is never returned."""
    return await _status(session, user.id)


@router.put("/llm-key", response_model=LLMKeyStatus)
async def put_llm_key(
    body: LLMKeyIn,
    user: CurrentUser,
    session: Session,
    llm: Annotated[LLMClient, Depends(get_llm_client)],
) -> LLMKeyStatus:
    api_key = body.api_key.strip()
    with llm_errors():
        await llm.verify_api_key(api_key)  # one tiny request; rejects bad keys before storing
    await save_key(session, user.id, api_key)
    await session.commit()
    return await _status(session, user.id)


@router.delete("/llm-key", status_code=status.HTTP_204_NO_CONTENT)
async def delete_llm_key(user: CurrentUser, session: Session) -> None:
    row = await get_key_row(session, user.id)
    if row is not None:
        await session.delete(row)
        await session.commit()


async def _hunter_status(session: AsyncSession, user_id: uuid.UUID) -> HunterKeyStatus:
    row = await get_service_key_row(session, user_id, ServiceKeyType.HUNTER)
    settings = get_settings()
    return HunterKeyStatus(
        configured=row is not None,
        verified_at=row.verified_at if row else None,
        owner_fallback_allowed=settings.allow_owner_hunter_fallback and bool(settings.hunter_api_key),
        searches_this_month=await contact_searches_this_month(session, user_id, datetime.now(UTC)),
        monthly_limit=settings.max_contact_lookups_per_user_month,
    )


@router.get("/hunter-key", response_model=HunterKeyStatus)
async def get_hunter_key(user: CurrentUser, session: Session) -> HunterKeyStatus:
    return await _hunter_status(session, user.id)


@router.put("/hunter-key", response_model=HunterKeyStatus)
async def put_hunter_key(
    body: HunterKeyIn,
    user: CurrentUser,
    session: Session,
    factory: Annotated[ProviderFactory, Depends(get_contact_provider_factory)],
) -> HunterKeyStatus:
    """Checked with Hunter's account endpoint (free, no credits) before it's stored."""
    api_key = body.api_key.strip()
    try:
        await factory(api_key).check_key()
    except ContactProviderAuthError as exc:
        raise api_error(
            status.HTTP_400_BAD_REQUEST,
            "hunter_key_invalid",
            f"Hunter didn't accept this key ({exc}). Log in to hunter.io to check the account.",
        ) from exc
    except ContactProviderError as exc:
        raise api_error(status.HTTP_502_BAD_GATEWAY, "hunter_unavailable", "Couldn't reach Hunter.") from exc
    await save_service_key(session, user.id, ServiceKeyType.HUNTER, api_key)
    await session.commit()
    return await _hunter_status(session, user.id)


@router.delete("/hunter-key", status_code=status.HTTP_204_NO_CONTENT)
async def delete_hunter_key(user: CurrentUser, session: Session) -> None:
    row = await get_service_key_row(session, user.id, ServiceKeyType.HUNTER)
    if row is not None:
        await session.delete(row)
        await session.commit()
