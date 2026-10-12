"""Delete my data (PLAN.md Phase 9): a hard delete of everything Sherlock holds for one user.

Removed: the user row and every user-owned row (all `user_id` FKs cascade: preferences, resumes,
matches, targets, outreach and its events, keys, tokens, usage), the user's files under
`STORAGE_DIR/{user_id}`, and Redis keys that name the user (cached Gmail access token, embeddings,
daily-run guards, rate-limit buckets). The Google authorisation is revoked first.

Kept, on purpose, because they protect the people who were emailed rather than describe the user:
the global suppression list and each contact's `last_contacted_at` (the 30-day cooldown, invariant 4).
Shared rows (companies, jobs, contacts) and the allowlist entry stay too; an admin removes the latter.
"""

import asyncio
import logging
import shutil
import uuid
from pathlib import Path

from redis.asyncio import Redis
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import User
from app.services.email.connection import GmailAccess, get_token_row
from app.services.google.oauth import GoogleOAuth

log = logging.getLogger(__name__)


async def _forget_redis_keys(redis: Redis, user_id: uuid.UUID) -> int:
    deleted = 0
    async for key in redis.scan_iter(match=f"*{user_id}*", count=500):
        deleted += int(await redis.delete(key))
    return deleted


async def delete_user_data(
    session: AsyncSession, user_id: uuid.UUID, oauth: GoogleOAuth | None, redis: Redis
) -> None:
    """Commits. Revoking at Google is best effort: a failure there doesn't keep the data."""
    if oauth is not None and await get_token_row(session, user_id) is not None:
        try:
            await GmailAccess(oauth, redis).revoke(session, user_id)
        except Exception:  # the token is deleted with the user either way
            log.warning("couldn't revoke the Google token for user %s", user_id, exc_info=True)
    await session.execute(delete(User).where(User.id == user_id))
    await session.commit()

    directory = Path(get_settings().storage_dir) / str(user_id)
    await asyncio.to_thread(shutil.rmtree, directory, ignore_errors=True)
    keys = await _forget_redis_keys(redis, user_id)
    log.info("deleted user %s (files removed, %d redis keys)", user_id, keys)
