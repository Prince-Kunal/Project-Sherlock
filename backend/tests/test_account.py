"""Delete my data (PLAN.md Phase 9): every row and file of the user goes, Gmail access is revoked, and
what protects the people who were emailed stays."""

import uuid
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis
from app.core.security import encrypt_secret
from app.models import (
    Base,
    Contact,
    OAuthToken,
    Outreach,
    SuppressionEntry,
    UsageLedger,
    User,
)
from app.models.enums import OAuthProvider, SuppressionReason, UsageProvider
from app.services.google.fake import FakeGoogleOAuth
from app.services.google.oauth import SCOPES
from app.services.registry import get_google_oauth
from tests.sending_fixtures import sendable, sender
from tests.test_matches_api import scored_user


async def _row_counts(session: AsyncSession, user_id: uuid.UUID) -> dict[str, int]:
    """Rows per user-owned table (every table with a user_id column)."""
    counts = {}
    for table in Base.metadata.sorted_tables:
        if "user_id" in table.c:
            counts[table.name] = int(
                await session.scalar(
                    select(func.count()).select_from(table).where(table.c.user_id == user_id)
                )
                or 0
            )
    return counts


async def test_delete_my_data_removes_everything_of_mine(
    auth_client: AsyncClient, session: AsyncSession, storage_dir: object
) -> None:
    from app.main import app

    me = uuid.UUID((await auth_client.get("/auth/me")).json()["id"])
    await scored_user(session, me)
    user = await session.get(User, me)
    assert user is not None
    outreach = await sendable(session, user)  # approved, with a PDF on disk
    contact = await session.get(Contact, outreach.contact_id)
    assert contact is not None
    contact.last_contacted_at = datetime.now(UTC)
    session.add(SuppressionEntry(email="optedout@corp.example", reason=SuppressionReason.OPT_OUT))
    session.add(
        OAuthToken(
            user_id=me,
            provider=OAuthProvider.GOOGLE,
            encrypted_refresh_token=encrypt_secret("refresh-dev"),
            scopes=list(SCOPES),
        )
    )
    session.add(UsageLedger(user_id=me, provider=UsageProvider.GEMINI, operation="draft_email", units=2))
    await session.commit()
    friend = await sender(session, "friend@example.com")
    friend_id, friends_outreach_id = friend.id, (await sendable(session, friend)).id
    await get_redis().set(f"gmail_access:{me}", "cached")
    await get_redis().set(f"gmail_access:{friend_id}", "cached")
    files = storage_dir / str(me)  # type: ignore[operator]
    assert files.is_dir()

    counts = await _row_counts(session, me)
    assert all(counts[t] > 0 for t in ("user_preferences", "master_resumes", "job_matches", "outreach"))

    oauth = FakeGoogleOAuth()
    app.dependency_overrides[get_google_oauth] = lambda: oauth
    try:
        refused = await auth_client.request("DELETE", "/settings/account", json={"confirm_email": "nope@x.y"})
        assert refused.status_code == 422
        response = await auth_client.request(
            "DELETE", "/settings/account", json={"confirm_email": "DEV@sherlock.local"}
        )
    finally:
        app.dependency_overrides.pop(get_google_oauth, None)
    assert response.status_code == 204
    assert "sherlock_session=" in response.headers["set-cookie"]

    session.expire_all()
    assert await session.get(User, me) is None
    assert set((await _row_counts(session, me)).values()) == {0}
    assert not files.exists()
    assert await get_redis().get(f"gmail_access:{me}") is None
    assert oauth.revoked == ["refresh-dev"]
    assert (await auth_client.get("/auth/me")).status_code == 401

    # What protects the people emailed, and other users' data, stays.
    assert await session.scalar(select(func.count()).select_from(SuppressionEntry)) == 1
    await session.refresh(contact)
    assert contact.last_contacted_at is not None
    assert await session.get(Outreach, friends_outreach_id) is not None
    assert await get_redis().get(f"gmail_access:{friend_id}") == "cached"
    assert (storage_dir / str(friend_id)).is_dir()  # type: ignore[operator]


async def test_a_failed_revoke_does_not_keep_the_data(
    auth_client: AsyncClient, session: AsyncSession
) -> None:
    from app.main import app

    me = uuid.UUID((await auth_client.get("/auth/me")).json()["id"])
    session.add(
        OAuthToken(
            user_id=me,
            provider=OAuthProvider.GOOGLE,
            encrypted_refresh_token=encrypt_secret("refresh-dev"),
            scopes=list(SCOPES),
        )
    )
    await session.commit()

    class Down(FakeGoogleOAuth):
        async def revoke(self, token: str) -> None:
            raise RuntimeError("google is down")

    app.dependency_overrides[get_google_oauth] = Down
    try:
        response = await auth_client.request(
            "DELETE", "/settings/account", json={"confirm_email": "dev@sherlock.local"}
        )
    finally:
        app.dependency_overrides.pop(get_google_oauth, None)
    assert response.status_code == 204
    session.expire_all()
    assert await session.get(User, me) is None
    assert await session.scalar(select(func.count()).select_from(OAuthToken)) == 0
