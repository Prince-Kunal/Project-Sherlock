"""Phase 7: Google sign-in run by the backend (allowlist, state + PKCE, encrypted refresh token),
Gmail connection status, reconnect and disconnect, and the access-token cache."""

import base64
import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
import respx
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.redis import get_redis
from app.models import AllowedEmail, OAuthToken, User
from app.services.email.connection import GmailAccess, get_token_row
from app.services.email.gmail import GmailNotConnectedError
from app.services.google.fake import FakeGoogleOAuth
from app.services.google.oauth import (
    GMAIL_SEND,
    TOKEN_URL,
    GoogleAuthError,
    GoogleReauthRequiredError,
    HttpGoogleOAuth,
)
from app.services.registry import get_google_oauth


@pytest.fixture
def google() -> Iterator[FakeGoogleOAuth]:
    from app.main import app

    fake = FakeGoogleOAuth()
    app.dependency_overrides[get_google_oauth] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_google_oauth, None)


async def _sign_in(client: AsyncClient, email: str, next_path: str | None = None) -> httpx.Response:
    start = await client.get("/auth/google/start", params={"next": next_path} if next_path else None)
    assert start.status_code == 302
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    return await client.get("/auth/google/callback", params={"code": email, "state": state})


async def _allow(session: AsyncSession, email: str) -> None:
    session.add(AllowedEmail(email=email))
    await session.commit()


async def test_start_sends_the_browser_to_google_with_pkce(
    client: AsyncClient, google: FakeGoogleOAuth
) -> None:
    response = await client.get("/auth/google/start")
    assert response.status_code == 302
    url = urlparse(response.headers["location"])
    assert url.netloc == "accounts.google.com"
    query = parse_qs(url.query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert GMAIL_SEND in query["scope"][0].split()
    assert "sherlock_oauth" in response.cookies
    assert (await client.get("/auth/config")).json() == {"dev_login": True, "google": True}


async def test_an_allowlisted_person_signs_in_and_the_token_is_stored_encrypted(
    client: AsyncClient, session: AsyncSession, google: FakeGoogleOAuth
) -> None:
    await _allow(session, "Friend@Example.com")
    response = await _sign_in(client, "friend@example.com", next_path="/tracker")
    assert response.status_code == 303
    assert response.headers["location"] == "/tracker"
    me = (await client.get("/auth/me")).json()
    assert me["email"] == "friend@example.com"
    assert me["is_admin"] is False

    user = await session.scalar(select(User).where(User.email == "friend@example.com"))
    assert user is not None
    row = await get_token_row(session, user.id)
    assert row is not None
    assert "refresh-friend@example.com" not in row.encrypted_refresh_token  # invariant 6
    assert GMAIL_SEND in row.scopes

    # The PKCE verifier sent to the token endpoint matches the challenge sent to Google.
    start = await client.get("/auth/google/start")
    challenge = parse_qs(urlparse(start.headers["location"]).query)["code_challenge"][0]
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    await client.get("/auth/google/callback", params={"code": "friend@example.com", "state": state})
    digest = hashlib.sha256(google.verifiers[-1].encode()).digest()
    assert base64.urlsafe_b64encode(digest).rstrip(b"=").decode() == challenge

    status = (await client.get("/settings/gmail")).json()
    assert status["connected"] is True
    assert status["needs_reauth"] is False


async def test_people_not_on_the_allowlist_are_turned_away(
    client: AsyncClient, session: AsyncSession, google: FakeGoogleOAuth
) -> None:
    response = await _sign_in(client, "stranger@example.com")
    assert response.headers["location"] == "/login?error=not_allowed"
    assert (await client.get("/auth/me")).status_code == 401
    assert await session.scalar(select(User).where(User.email == "stranger@example.com")) is None


async def test_admin_emails_may_always_sign_in_as_admins(
    client: AsyncClient, google: FakeGoogleOAuth, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "admin_emails", ["Owner@Example.com"])
    response = await _sign_in(client, "owner@example.com")
    assert response.headers["location"] == "/review"
    assert (await client.get("/auth/me")).json()["is_admin"] is True


@pytest.mark.parametrize(
    ("params", "error"),
    [
        ({"code": "friend@example.com", "state": "forged"}, "state"),
        ({"error": "access_denied", "state": "x"}, "denied"),
    ],
)
async def test_bad_callbacks_are_refused(
    client: AsyncClient, session: AsyncSession, google: FakeGoogleOAuth, params: dict[str, str], error: str
) -> None:
    await _allow(session, "friend@example.com")
    await client.get("/auth/google/start")
    response = await client.get("/auth/google/callback", params=params)
    assert response.headers["location"] == f"/login?error={error}"
    assert (await client.get("/auth/me")).status_code == 401


async def test_a_callback_without_the_state_cookie_is_refused(
    client: AsyncClient, google: FakeGoogleOAuth
) -> None:
    response = await client.get("/auth/google/callback", params={"code": "a@b.co", "state": "x"})
    assert response.headers["location"] == "/login?error=expired"


async def test_next_must_stay_on_this_site(
    client: AsyncClient, session: AsyncSession, google: FakeGoogleOAuth
) -> None:
    await _allow(session, "friend@example.com")
    for bad in ("//evil.example/x", "https://evil.example", "/\\evil.example"):
        response = await _sign_in(client, "friend@example.com", next_path=bad)
        assert response.headers["location"] == "/review", bad


async def test_unticked_gmail_permissions_show_as_missing(
    client: AsyncClient, session: AsyncSession, google: FakeGoogleOAuth
) -> None:
    await _allow(session, "friend@example.com")
    google.scopes = ["openid", "email", "profile"]
    await _sign_in(client, "friend@example.com")
    status = (await client.get("/settings/gmail")).json()
    assert (status["connected"], status["missing_permissions"]) == (False, True)


async def test_reconnecting_clears_needs_reauth_and_disconnect_revokes(
    client: AsyncClient, session: AsyncSession, google: FakeGoogleOAuth
) -> None:
    await _allow(session, "friend@example.com")
    await _sign_in(client, "friend@example.com")
    user = await session.scalar(select(User).where(User.email == "friend@example.com"))
    assert user is not None
    row = await get_token_row(session, user.id)
    assert row is not None
    row.needs_reauth = True
    await session.commit()
    assert (await client.get("/settings/gmail")).json()["needs_reauth"] is True

    await _sign_in(client, "friend@example.com")
    assert (await client.get("/settings/gmail")).json() | {"connected_at": None} == {
        "connected": True,
        "email": "friend@example.com",
        "needs_reauth": False,
        "missing_permissions": False,
        "connected_at": None,
        "paused": False,
        "google_sign_in": True,
    }

    assert (await client.delete("/settings/gmail")).status_code == 204
    assert google.revoked == ["refresh-friend@example.com"]
    assert await session.scalar(select(OAuthToken).where(OAuthToken.user_id == user.id)) is None
    assert (await client.get("/settings/gmail")).json()["connected"] is False


async def test_access_tokens_are_cached_and_expiry_is_reported(
    session: AsyncSession, google: FakeGoogleOAuth
) -> None:
    from tests.sending_fixtures import sender
    from tests.test_sending import _tokens

    user = await sender(session)
    from app.services.email.connection import save_google_tokens

    await save_google_tokens(session, user.id, _tokens(user.email))
    await session.commit()
    access = GmailAccess(google, get_redis())
    client = await access(session, user)
    token_source = client._token  # type: ignore[attr-defined]
    assert await token_source(False) == "access-for-refresh-1"
    assert await token_source(False) == "access-for-refresh-1"
    assert google.refreshes == 1  # the second came from the (encrypted) Redis cache
    cached = await get_redis().get(f"gmail_access:{user.id}")
    assert cached is not None
    assert "access-for-refresh-1" not in str(cached)

    google.expired.add("refresh-1")
    with pytest.raises(GoogleReauthRequiredError):
        await token_source(True)

    row = await get_token_row(session, user.id)
    assert row is not None
    row.needs_reauth = True
    await session.commit()
    with pytest.raises(GmailNotConnectedError):
        await access(session, user)


async def test_allowlist_admin(auth_client: AsyncClient, other_user_headers: dict[str, str]) -> None:
    added = await auth_client.post("/admin/allowed-emails", json={"email": "Friend@Example.com"})
    assert added.status_code == 201
    assert added.json()["email"] == "friend@example.com"
    emails = [r["email"] for r in (await auth_client.get("/admin/allowed-emails")).json()]
    assert "friend@example.com" in emails
    assert (
        await auth_client.post("/admin/allowed-emails", json={"email": "not-an-email"})
    ).status_code == 422
    assert (await auth_client.get("/admin/allowed-emails", headers=other_user_headers)).status_code == 403
    assert (await auth_client.delete("/admin/allowed-emails/friend@example.com")).status_code == 204
    me = (await auth_client.get("/auth/me")).json()["email"]
    assert (await auth_client.delete(f"/admin/allowed-emails/{me}")).json()["detail"][
        "code"
    ] == "cannot_remove_self"


# --- The real HTTP adapter, against Google's documented responses ----------------------------------


def _id_token(**claims: object) -> str:
    now = datetime.now(UTC)
    base = {
        "iss": "https://accounts.google.com",
        "aud": "client-1",
        "sub": "1234567890",
        "email": "Friend@Example.com",
        "email_verified": True,
        "name": "Friend",
        "iat": now,
        "exp": now + timedelta(hours=1),
    }
    return jwt.encode({**base, **claims}, "google-signs-these-with-its-own-keys-not-us", algorithm="HS256")


@respx.mock
async def test_http_adapter_exchanges_the_code() -> None:
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "ya29.a",
                "expires_in": 3599,
                "refresh_token": "1//r",
                "scope": f"openid {GMAIL_SEND} https://www.googleapis.com/auth/userinfo.email",
                "token_type": "Bearer",
                "id_token": _id_token(),
            },
        )
    )
    oauth = HttpGoogleOAuth("client-1", "secret-1", "http://localhost:3000/api/auth/google/callback")
    tokens = await oauth.exchange_code("4/code", "verifier-1")
    assert tokens.identity.email == "friend@example.com"
    assert tokens.refresh_token == "1//r"
    assert GMAIL_SEND in tokens.scopes
    sent = parse_qs(route.calls.last.request.content.decode())
    assert sent["code_verifier"] == ["verifier-1"]
    assert sent["grant_type"] == ["authorization_code"]


@respx.mock
@pytest.mark.parametrize("claims", [{"aud": "someone-else"}, {"iss": "https://evil.example"}])
async def test_http_adapter_rejects_id_tokens_not_meant_for_us(claims: dict[str, str]) -> None:
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "a", "id_token": _id_token(**claims)})
    )
    with pytest.raises(GoogleAuthError):
        await HttpGoogleOAuth("client-1", "s", "http://x/cb").exchange_code("c", "v")


@respx.mock
async def test_http_adapter_maps_invalid_grant_to_reauth() -> None:
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            400,
            content=json.dumps(
                {"error": "invalid_grant", "error_description": "Token has been expired or revoked."}
            ),
        )
    )
    with pytest.raises(GoogleReauthRequiredError, match="expired"):
        await HttpGoogleOAuth("client-1", "s", "http://x/cb").refresh("1//old")
