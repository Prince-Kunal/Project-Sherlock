from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import SESSION_COOKIE, CurrentUser, create_session_token
from app.core.config import get_settings
from app.core.db import get_session
from app.models import AllowedEmail, User, UserPreferences
from app.schemas.user import SessionOut, UserOut

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


@router.post("/dev-login", response_model=SessionOut)
async def dev_login(response: Response, session: Annotated[AsyncSession, Depends(get_session)]) -> SessionOut:
    settings = get_settings()
    if not settings.dev_auth:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    user = await ensure_dev_user(session)
    token = create_session_token(user.id)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.env == "production",
        max_age=settings.session_ttl_hours * 3600,
    )
    return SessionOut(token=token, user=UserOut.model_validate(user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
