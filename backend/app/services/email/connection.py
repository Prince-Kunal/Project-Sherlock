"""A user's Gmail connection (PLAN.md Phase 7): the stored Google tokens and a Gmail client for them.

The refresh token is kept Fernet-encrypted in `oauth_tokens` (invariant 6); short-lived access
tokens are cached in Redis, encrypted too. When Google says the refresh token is expired or revoked
(`invalid_grant`, every ~7 days in Testing mode) the caller marks the row `needs_reauth`, which
pauses sending and shows the "Reconnect Gmail" banner.
"""

import uuid
from collections.abc import Awaitable, Callable

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decrypt_secret, encrypt_secret
from app.models import OAuthToken, User
from app.models.enums import OAuthProvider
from app.services.email.gmail import GmailApiClient, GmailClient, GmailNotConnectedError
from app.services.google.oauth import GMAIL_SCOPES, GoogleOAuth, GoogleTokens

GmailFactory = Callable[[AsyncSession, User], Awaitable[GmailClient]]


def _cache_key(user_id: uuid.UUID) -> str:
    return f"gmail_access:{user_id}"


async def get_token_row(session: AsyncSession, user_id: uuid.UUID) -> OAuthToken | None:
    return await session.scalar(select(OAuthToken).where(OAuthToken.user_id == user_id))


def has_gmail_scopes(row: OAuthToken) -> bool:
    return set(row.scopes or []) >= GMAIL_SCOPES


def gmail_usable(row: OAuthToken | None) -> bool:
    return row is not None and not row.needs_reauth and has_gmail_scopes(row)


async def save_google_tokens(
    session: AsyncSession, user_id: uuid.UUID, tokens: GoogleTokens, redis: Redis | None = None
) -> OAuthToken:
    """Store (or refresh) the user's Google authorisation. Caller commits."""
    row = await get_token_row(session, user_id)
    if row is None:
        if tokens.refresh_token is None:
            raise GmailNotConnectedError("Google didn't return a refresh token")
        row = OAuthToken(user_id=user_id, provider=OAuthProvider.GOOGLE, encrypted_refresh_token="")
        session.add(row)
    if tokens.refresh_token is not None:
        row.encrypted_refresh_token = encrypt_secret(tokens.refresh_token)
    row.scopes = sorted(set(tokens.scopes))
    row.needs_reauth = False
    await session.flush()
    if redis is not None:
        await redis.delete(_cache_key(user_id))
    return row


async def mark_needs_reauth(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Pause sending until the user reconnects Gmail. Caller commits."""
    row = await get_token_row(session, user_id)
    if row is not None:
        row.needs_reauth = True


class GmailAccess:
    """Builds a Gmail client for a user from their stored authorisation."""

    def __init__(self, oauth: GoogleOAuth, redis: Redis) -> None:
        self._oauth = oauth
        self._redis = redis

    async def __call__(self, session: AsyncSession, user: User) -> GmailClient:
        row = await get_token_row(session, user.id)
        if row is None or not gmail_usable(row):
            raise GmailNotConnectedError("Gmail isn't connected or needs reconnecting")
        refresh_token = decrypt_secret(row.encrypted_refresh_token)
        key = _cache_key(user.id)

        async def token_source(force_refresh: bool) -> str:
            if not force_refresh and (cached := await self._redis.get(key)):
                return decrypt_secret(cached.decode() if isinstance(cached, bytes) else cached)
            access = await self._oauth.refresh(refresh_token)  # raises GoogleReauthRequiredError
            await self._redis.set(key, encrypt_secret(access.token), ex=max(60, access.expires_in - 120))
            return access.token

        return GmailApiClient(token_source, user.email, user.name)

    async def revoke(self, session: AsyncSession, user_id: uuid.UUID) -> None:
        """Disconnect: revoke at Google (best effort) and forget the tokens. Caller commits."""
        row = await get_token_row(session, user_id)
        if row is not None:
            await self._oauth.revoke(decrypt_secret(row.encrypted_refresh_token))
            await session.delete(row)
        await self._redis.delete(_cache_key(user_id))
