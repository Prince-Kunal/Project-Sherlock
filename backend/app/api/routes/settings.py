import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import api_error, llm_errors
from app.core.auth import SESSION_COOKIE, CurrentUser
from app.core.config import get_settings
from app.core.db import get_session
from app.core.redis import get_redis
from app.models.enums import ServiceKeyType
from app.schemas.settings import (
    ApolloKeyStatus,
    DeleteAccountIn,
    GmailStatus,
    HunterKeyIn,
    HunterKeyStatus,
    LLMKeyIn,
    LLMKeyStatus,
    QuotaOut,
)
from app.services.account import delete_user_data
from app.services.contacts.base import ContactProviderAuthError, ContactProviderError
from app.services.contacts.keys import get_service_key_row, save_service_key
from app.services.contacts.service import APOLLO_SEARCH_OPERATION, ProviderFactory
from app.services.email.connection import GmailAccess, get_token_row, gmail_usable, has_gmail_scopes
from app.services.google.oauth import GoogleOAuth
from app.services.llm.client import LLMClient
from app.services.llm.user_keys import FREE_TIER_NOTICE, get_key_row, save_key
from app.services.matching.pipeline import load_preferences
from app.services.quotas import contact_lookups_this_month, quota_status
from app.services.registry import (
    get_apollo_factory,
    get_contact_provider_factory,
    get_google_oauth,
    get_llm_client,
)
from app.services.usage import llm_calls_since

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
        searches_this_month=await contact_lookups_this_month(session, user_id, datetime.now(UTC)),
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


# --- Apollo (PLAN.md Phase 8, optional) --------------------------------------------------------------


async def _apollo_status(session: AsyncSession, user_id: uuid.UUID) -> ApolloKeyStatus:
    row = await get_service_key_row(session, user_id, ServiceKeyType.APOLLO)
    now = datetime.now(UTC)
    month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return ApolloKeyStatus(
        configured=row is not None,
        verified_at=row.verified_at if row else None,
        searches_this_month=await llm_calls_since(session, user_id, APOLLO_SEARCH_OPERATION, month),
    )


@router.get("/apollo-key", response_model=ApolloKeyStatus)
async def get_apollo_key(user: CurrentUser, session: Session) -> ApolloKeyStatus:
    return await _apollo_status(session, user.id)


@router.put("/apollo-key", response_model=ApolloKeyStatus)
async def put_apollo_key(
    body: HunterKeyIn,
    user: CurrentUser,
    session: Session,
    factory: Annotated[ProviderFactory, Depends(get_apollo_factory)],
) -> ApolloKeyStatus:
    """Optional: with an Apollo key, people are searched on Apollo before Hunter. Checked with
    Apollo's auth health endpoint (free) before it's stored."""
    api_key = body.api_key.strip()
    try:
        await factory(api_key).check_key()
    except ContactProviderAuthError as exc:
        raise api_error(
            status.HTTP_400_BAD_REQUEST,
            "apollo_key_invalid",
            f"Apollo didn't accept this key ({exc}). Search needs an account registered with a work email.",
        ) from exc
    except ContactProviderError as exc:
        raise api_error(status.HTTP_502_BAD_GATEWAY, "apollo_unavailable", "Couldn't reach Apollo.") from exc
    await save_service_key(session, user.id, ServiceKeyType.APOLLO, api_key)
    await session.commit()
    return await _apollo_status(session, user.id)


@router.delete("/apollo-key", status_code=status.HTTP_204_NO_CONTENT)
async def delete_apollo_key(user: CurrentUser, session: Session) -> None:
    row = await get_service_key_row(session, user.id, ServiceKeyType.APOLLO)
    if row is not None:
        await session.delete(row)
        await session.commit()


# --- Gmail (PLAN.md Phase 7) ---------------------------------------------------------------------


@router.get("/gmail", response_model=GmailStatus)
async def gmail_status(
    user: CurrentUser, session: Session, oauth: Annotated[GoogleOAuth | None, Depends(get_google_oauth)]
) -> GmailStatus:
    row = await get_token_row(session, user.id)
    prefs = await load_preferences(session, user.id)
    return GmailStatus(
        connected=gmail_usable(row),
        email=user.email,
        needs_reauth=bool(row and row.needs_reauth),
        missing_permissions=bool(row and not has_gmail_scopes(row)),
        connected_at=row.updated_at if row else None,
        paused=prefs.paused,
        google_sign_in=oauth is not None,
    )


@router.delete("/gmail", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_gmail(
    user: CurrentUser, session: Session, oauth: Annotated[GoogleOAuth | None, Depends(get_google_oauth)]
) -> None:
    """Revoke Sherlock's access at Google and forget the tokens. Scheduled emails wait until Gmail is
    connected again."""
    if oauth is not None:
        await GmailAccess(oauth, get_redis()).revoke(session, user.id)
    elif (row := await get_token_row(session, user.id)) is not None:
        await session.delete(row)
    await session.commit()


# --- Quotas and account (PLAN.md Phase 9) -------------------------------------------------------------


@router.get("/quota", response_model=QuotaOut)
async def get_quota(user: CurrentUser, session: Session) -> QuotaOut:
    status_ = await quota_status(session, user.id)
    return QuotaOut(
        contact_lookups=status_.contact_lookups,
        contact_lookups_limit=status_.contact_lookups_limit,
        llm_usd=status_.llm_usd,
        llm_usd_limit=status_.llm_usd_limit,
        exceeded=status_.exceeded,
        message=status_.message,
        resets_at=status_.resets_at,
    )


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    body: DeleteAccountIn,
    user: CurrentUser,
    session: Session,
    response: Response,
    oauth: Annotated[GoogleOAuth | None, Depends(get_google_oauth)],
) -> None:
    """Delete my data: every row and file Sherlock holds for this user, and Gmail access revoked.
    The address must be typed back as confirmation."""
    if body.confirm_email.strip().lower() != user.email.lower():
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "confirm_email_mismatch",
            "Type your email address exactly.",
        )
    await delete_user_data(session, user.id, oauth, get_redis())
    response.delete_cookie(SESSION_COOKIE)
