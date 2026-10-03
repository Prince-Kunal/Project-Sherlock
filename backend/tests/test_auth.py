import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import SESSION_COOKIE, create_session_token
from app.core.config import Settings, get_settings
from app.models import AllowedEmail, User, UserPreferences


async def test_request_without_session_is_401(client: AsyncClient) -> None:
    response = await client.get("/auth/me")
    assert response.status_code == 401


async def test_garbage_token_is_401(client: AsyncClient) -> None:
    response = await client.get("/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401


async def test_expired_token_is_401(client: AsyncClient) -> None:
    past = datetime.now(UTC) - timedelta(hours=1)
    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "iat": past, "exp": past}, get_settings().auth_secret, algorithm="HS256"
    )
    response = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


async def test_token_for_unknown_user_is_401(client: AsyncClient) -> None:
    token = create_session_token(uuid.uuid4())
    response = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


async def test_dev_login_issues_working_session(client: AsyncClient, session: AsyncSession) -> None:
    response = await client.post("/auth/dev-login")
    assert response.status_code == 200
    assert SESSION_COOKIE in response.cookies
    body = response.json()
    assert body["user"]["email"] == get_settings().dev_user_email

    # The cookie alone authenticates subsequent requests.
    me = await client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["id"] == body["user"]["id"]

    # Bearer token works too.
    client.cookies.clear()
    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert me.status_code == 200

    # Seeded user is allowlisted and has default preferences.
    user = (await session.execute(select(User).where(User.email == body["user"]["email"]))).scalar_one()
    assert (await session.execute(select(AllowedEmail).where(AllowedEmail.email == user.email))).scalar_one()
    prefs = (
        await session.execute(select(UserPreferences).where(UserPreferences.user_id == user.id))
    ).scalar_one()
    assert prefs.daily_send_cap == 15
    assert prefs.open_outreach_share == 40


async def test_dev_login_is_idempotent(client: AsyncClient, session: AsyncSession) -> None:
    first = (await client.post("/auth/dev-login")).json()
    second = (await client.post("/auth/dev-login")).json()
    assert first["user"]["id"] == second["user"]["id"]
    users = (await session.execute(select(User))).scalars().all()
    assert len(users) == 1


async def test_logout_clears_session(client: AsyncClient) -> None:
    await client.post("/auth/dev-login")
    assert (await client.get("/auth/me")).status_code == 200
    await client.post("/auth/logout")
    assert (await client.get("/auth/me")).status_code == 401


async def test_dev_login_disabled_without_dev_auth(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "dev_auth", False)
    response = await client.post("/auth/dev-login")
    assert response.status_code == 404


def test_dev_auth_refused_in_production() -> None:
    with pytest.raises(ValueError, match="DEV_AUTH"):
        Settings(env="production", dev_auth=True)
