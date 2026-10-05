"""Session tokens and the `current_user` dependency.

Phase 0: sessions are HS256 JWTs signed with AUTH_SECRET, issued by the dev-login stub.
Phase 7 replaces the issuer with Auth.js (Google) but keeps `current_user` as the single entry point.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.models import User

SESSION_COOKIE = "sherlock_session"
_ALGORITHM = "HS256"


def _secret() -> str:
    secret = get_settings().auth_secret
    if not secret:
        raise RuntimeError("AUTH_SECRET is not set")
    return secret


def create_session_token(user_id: uuid.UUID) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(hours=get_settings().session_ttl_hours),
    }
    return jwt.encode(claims, _secret(), algorithm=_ALGORITHM)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _token_from_request(request: Request) -> str | None:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return request.cookies.get(SESSION_COOKIE)


def decode_session_token(token: str) -> uuid.UUID:
    try:
        claims = jwt.decode(token, _secret(), algorithms=[_ALGORITHM], options={"require": ["sub", "exp"]})
        return uuid.UUID(claims["sub"])
    except (jwt.PyJWTError, ValueError) as exc:
        raise _unauthorized() from exc


async def get_current_user(request: Request, session: Annotated[AsyncSession, Depends(get_session)]) -> User:
    token = _token_from_request(request)
    if token is None:
        raise _unauthorized()
    user = await session.get(User, decode_session_token(token))
    if user is None or not user.is_active:
        raise _unauthorized()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_admin_user(user: CurrentUser) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admins only")
    return user


AdminUser = Annotated[User, Depends(get_admin_user)]
