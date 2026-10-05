from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser
from app.core.db import get_session
from app.models import User, UserPreferences
from app.schemas.preferences import PreferencesIn, PreferencesOut

router = APIRouter(prefix="/preferences", tags=["preferences"])

Session = Annotated[AsyncSession, Depends(get_session)]


async def _get_or_create(session: AsyncSession, user: User) -> UserPreferences:
    result = await session.execute(select(UserPreferences).where(UserPreferences.user_id == user.id))
    prefs = result.scalar_one_or_none()
    if prefs is None:
        prefs = UserPreferences(user_id=user.id)
        session.add(prefs)
        await session.flush()
        await session.refresh(prefs)
    return prefs


def _out(prefs: UserPreferences, user: User) -> PreferencesOut:
    fields = {name: getattr(prefs, name) for name in PreferencesOut.model_fields if name != "timezone"}
    return PreferencesOut(**fields, timezone=user.timezone)


@router.get("", response_model=PreferencesOut)
async def get_preferences(user: CurrentUser, session: Session) -> PreferencesOut:
    prefs = await _get_or_create(session, user)
    await session.commit()
    return _out(prefs, user)


@router.put("", response_model=PreferencesOut)
async def put_preferences(body: PreferencesIn, user: CurrentUser, session: Session) -> PreferencesOut:
    prefs = await _get_or_create(session, user)
    for name, value in body.model_dump(exclude={"timezone"}).items():
        setattr(prefs, name, value)
    user.timezone = body.timezone
    await session.commit()
    await session.refresh(prefs)
    return _out(prefs, user)
