"""Each user's own Gemini key (BYOK, PLAN.md §3.1), stored Fernet-encrypted (invariant 6)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import decrypt_secret, encrypt_secret
from app.models import UserLLMKey
from app.models.enums import LLMProvider

FREE_TIER_NOTICE = (
    "Google may use prompts and responses sent with free-tier keys to improve its products, and human "
    "reviewers may read them. Sherlock never sends your phone number, email address or home address, "
    "and refers to contacts by first name and role only."
)


class LLMKeyRequiredError(Exception):
    """The user has no key and the owner's key may not be used as a fallback."""


async def get_key_row(session: AsyncSession, user_id: uuid.UUID) -> UserLLMKey | None:
    result = await session.execute(select(UserLLMKey).where(UserLLMKey.user_id == user_id))
    return result.scalar_one_or_none()


async def save_key(session: AsyncSession, user_id: uuid.UUID, api_key: str) -> UserLLMKey:
    """Store an already-verified key. Caller commits."""
    row = await get_key_row(session, user_id)
    if row is None:
        row = UserLLMKey(user_id=user_id, provider=LLMProvider.GEMINI, encrypted_api_key="")
        session.add(row)
    row.provider = LLMProvider.GEMINI
    row.encrypted_api_key = encrypt_secret(api_key)
    row.verified_at = datetime.now(UTC)
    row.last_quota_exhausted_at = None
    await session.flush()
    return row


async def resolve_api_key(session: AsyncSession, user_id: uuid.UUID) -> str | None:
    """The key to use for this user's LLM work. None means "use the owner's key" (only when allowed)."""
    row = await get_key_row(session, user_id)
    if row is not None:
        return decrypt_secret(row.encrypted_api_key)
    if get_settings().allow_owner_key_fallback:
        return None
    raise LLMKeyRequiredError
