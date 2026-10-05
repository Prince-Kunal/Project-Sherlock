"""Each user's own Hunter key (decided for Phase 5: the free plan's ~50 credits/month are per
account, so one shared key can't serve a group). Stored Fernet-encrypted (invariant 6)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import decrypt_secret, encrypt_secret
from app.models import UserServiceKey
from app.models.enums import ServiceKeyType


async def get_service_key_row(
    session: AsyncSession, user_id: uuid.UUID, service: ServiceKeyType
) -> UserServiceKey | None:
    return await session.scalar(
        select(UserServiceKey).where(UserServiceKey.user_id == user_id, UserServiceKey.service == service)
    )


async def save_service_key(
    session: AsyncSession, user_id: uuid.UUID, service: ServiceKeyType, api_key: str
) -> UserServiceKey:
    """Store an already-verified key. Caller commits."""
    row = await get_service_key_row(session, user_id, service)
    if row is None:
        row = UserServiceKey(user_id=user_id, service=service, encrypted_api_key="")
        session.add(row)
    row.encrypted_api_key = encrypt_secret(api_key)
    row.verified_at = datetime.now(UTC)
    row.quota_exhausted_at = None
    await session.flush()
    return row


async def resolve_hunter_key(session: AsyncSession, user_id: uuid.UUID) -> str | None:
    """The user's Hunter key; else the owner's when the fallback is allowed; else None (then only
    contacts already in the database can be used)."""
    row = await get_service_key_row(session, user_id, ServiceKeyType.HUNTER)
    if row is not None:
        return decrypt_secret(row.encrypted_api_key)
    settings = get_settings()
    if settings.allow_owner_hunter_fallback and settings.hunter_api_key:
        return settings.hunter_api_key
    return None
