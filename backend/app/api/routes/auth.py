"""Sign-in (PLAN.md Phase 7): Google OAuth run by the backend, plus the local dev-login stub.

Google sign-in also authorises Gmail (send + read), so one consent screen does both. Only allowlisted
addresses (or ADMIN_EMAILS) may sign in. The session is the same HS256 cookie dev-login issues.
"""

import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import SESSION_COOKIE, CurrentUser, create_session_token, decode_session_token
from app.core.config import get_settings
from app.core.db import get_session
from app.core.redis import get_redis
from app.models import AllowedEmail, User, UserPreferences
from app.schemas.user import SessionOut, UserOut
from app.services.email.connection import save_google_tokens
from app.services.email.gmail import GmailNotConnectedError
from app.services.google.oauth import GoogleAuthError, GoogleOAuth, pkce_pair
from app.services.registry import get_google_oauth

router = APIRouter(prefix="/auth", tags=["auth"])


async def ensure_dev_user(session: AsyncSession) -> User:
    """Idempotently seed the local dev user (allowlisted, admin, with default preferences)."""
    email = get_settings().dev_user_email.lower()
    user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None:
        user = User(email=email, name="Dev User", is_admin=True)
        session.add(user)
        await session.flush()
        session.add(UserPreferences(user_id=user.id))
    allowed = await session.execute(select(AllowedEmail).where(AllowedEmail.email == email))
    if allowed.scalar_one_or_none() is None:
        session.add(AllowedEmail(email=email))
    await session.commit()
    await session.refresh(user)
    return user


def _set_session_cookie(response: Response, user: User) -> str:
    settings = get_settings()
    token = create_session_token(user.id)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.env == "production",
        max_age=settings.session_ttl_hours * 3600,
    )
    return token


@router.post("/dev-login", response_model=SessionOut)
async def dev_login(response: Response, session: Annotated[AsyncSession, Depends(get_session)]) -> SessionOut:
    settings = get_settings()
    if not settings.dev_auth:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    user = await ensure_dev_user(session)
    token = _set_session_cookie(response, user)
    return SessionOut(token=token, user=UserOut.model_validate(user))


class AuthConfig(BaseModel):
    dev_login: bool
    google: bool


@router.get("/config", response_model=AuthConfig)
async def auth_config(oauth: Annotated[GoogleOAuth | None, Depends(get_google_oauth)]) -> AuthConfig:
    """Which sign-in buttons the login page shows."""
    return AuthConfig(dev_login=get_settings().dev_auth, google=oauth is not None)


# --- Google ----------------------------------------------------------------------------------------

OAUTH_COOKIE = "sherlock_oauth"
OAUTH_COOKIE_MINUTES = 10


def _safe_next(path: str | None) -> str:
    """Only same-site paths: "/review", never "//evil.example" or "https://…"."""
    if not path or not path.startswith("/") or path.startswith("//") or "\\" in path:
        return "/review"
    return path


def _login_error(code: str) -> RedirectResponse:
    response = RedirectResponse(f"/login?error={code}", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(OAUTH_COOKIE)
    return response


def _require_oauth(oauth: GoogleOAuth | None) -> GoogleOAuth:
    if oauth is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "google_not_configured",
                "message": "Google sign-in isn't set up on this server.",
            },
        )
    return oauth


@router.get("/google/start")
async def google_start(
    request: Request,
    oauth: Annotated[GoogleOAuth | None, Depends(get_google_oauth)],
    session: Annotated[AsyncSession, Depends(get_session)],
    next: str | None = None,
) -> RedirectResponse:
    """Send the browser to Google's consent screen. The state and PKCE verifier ride in a short-lived
    signed cookie so the callback can check them."""
    oauth = _require_oauth(oauth)
    state = secrets.token_urlsafe(24)
    verifier, challenge = pkce_pair()
    hint = None
    if token := request.cookies.get(SESSION_COOKIE):  # reconnecting: preselect the account
        try:
            user = await session.get(User, decode_session_token(token))
            hint = user.email if user else None
        except HTTPException:
            hint = None
    now = datetime.now(UTC)
    payload = {
        "state": state,
        "verifier": verifier,
        "next": _safe_next(next),
        "exp": now + timedelta(minutes=OAUTH_COOKIE_MINUTES),
    }
    response = RedirectResponse(
        oauth.authorization_url(state, challenge, hint), status_code=status.HTTP_302_FOUND
    )
    response.set_cookie(
        OAUTH_COOKIE,
        jwt.encode(payload, get_settings().auth_secret, algorithm="HS256"),
        httponly=True,
        samesite="lax",  # sent on Google's top-level redirect back
        secure=get_settings().env == "production",
        max_age=OAUTH_COOKIE_MINUTES * 60,
    )
    return response


async def is_allowed(session: AsyncSession, email: str) -> bool:
    if email in {e.lower() for e in get_settings().admin_emails}:
        return True
    return (
        await session.scalar(select(AllowedEmail.id).where(func.lower(AllowedEmail.email) == email))
        is not None
    )


@router.get("/google/callback")
async def google_callback(
    request: Request,
    oauth: Annotated[GoogleOAuth | None, Depends(get_google_oauth)],
    session: Annotated[AsyncSession, Depends(get_session)],
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    oauth = _require_oauth(oauth)
    try:
        cookie = jwt.decode(
            request.cookies.get(OAUTH_COOKIE, ""), get_settings().auth_secret, algorithms=["HS256"]
        )
    except jwt.PyJWTError:
        return _login_error("expired")
    if error:
        return _login_error("denied" if error == "access_denied" else "google")
    if not code or not state or not secrets.compare_digest(state, str(cookie.get("state", ""))):
        return _login_error("state")
    try:
        tokens = await oauth.exchange_code(code, str(cookie["verifier"]))
    except GoogleAuthError:
        return _login_error("google")
    identity = tokens.identity
    if not identity.email or not identity.email_verified:
        return _login_error("unverified")
    if not await is_allowed(session, identity.email):
        return _login_error("not_allowed")

    user = await session.scalar(select(User).where(func.lower(User.email) == identity.email))
    admin = identity.email in {e.lower() for e in get_settings().admin_emails}
    if user is None:
        user = User(email=identity.email, name=identity.name, is_admin=admin)
        session.add(user)
        await session.flush()
        session.add(UserPreferences(user_id=user.id))
    elif not user.is_active:
        return _login_error("not_allowed")
    else:
        user.name = user.name or identity.name
        user.is_admin = user.is_admin or admin
    try:
        await save_google_tokens(session, user.id, tokens, get_redis())
    except GmailNotConnectedError:  # no refresh token came back
        return _login_error("google")
    await session.commit()

    response = RedirectResponse(_safe_next(cookie.get("next")), status_code=status.HTTP_303_SEE_OTHER)
    _set_session_cookie(response, user)
    response.delete_cookie(OAUTH_COOKIE)
    return response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
