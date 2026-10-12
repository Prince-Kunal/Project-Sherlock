"""Onboarding for a new friend (PLAN.md Phase 9): sign in → connect Gmail → add keys → upload resume →
review the parsed resume → set preferences → first run. The frontend's /welcome page walks through it;
this reports which steps the data already satisfies and finishes the flow."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import api_error
from app.core.auth import CurrentUser
from app.core.db import get_session
from app.models import User
from app.schemas.onboarding import OnboardingCompleteIn, OnboardingStatus
from app.services.contacts.keys import resolve_hunter_key
from app.services.email.connection import get_token_row, gmail_usable
from app.services.google.oauth import GoogleOAuth
from app.services.llm.user_keys import LLMKeyRequiredError, resolve_api_key
from app.services.matching.pipeline import load_preferences
from app.services.registry import get_google_oauth
from app.services.resume import store
from app.workers.queue import enqueue

router = APIRouter(prefix="/onboarding", tags=["onboarding"])

Session = Annotated[AsyncSession, Depends(get_session)]
OAuth = Annotated[GoogleOAuth | None, Depends(get_google_oauth)]


async def _has_llm_key(session: AsyncSession, user_id: uuid.UUID) -> bool:
    try:
        await resolve_api_key(session, user_id)
    except LLMKeyRequiredError:
        return False
    return True


async def _status(session: AsyncSession, user: User, oauth: GoogleOAuth | None) -> OnboardingStatus:
    prefs = await load_preferences(session, user.id)
    return OnboardingStatus(
        google_sign_in=oauth is not None,
        gmail=gmail_usable(await get_token_row(session, user.id)),
        llm_key=await _has_llm_key(session, user.id),
        hunter_key=await resolve_hunter_key(session, user.id) is not None,
        resume=await store.get_current(session, user.id) is not None,
        preferences=bool(prefs.target_roles) and bool(prefs.employment_types),
        completed=user.onboarded_at is not None,
    )


@router.get("", response_model=OnboardingStatus)
async def onboarding_status(user: CurrentUser, session: Session, oauth: OAuth) -> OnboardingStatus:
    return await _status(session, user, oauth)


@router.post("/complete", response_model=OnboardingStatus)
async def complete(
    body: OnboardingCompleteIn, user: CurrentUser, session: Session, oauth: OAuth
) -> OnboardingStatus:
    """Finish onboarding. With `start`, the first run is queued: jobs are scored for this user and then
    today's drafts are built, so the review queue fills without waiting for 07:00."""
    current = await _status(session, user, oauth)
    if body.start and not (current.llm_key and current.resume and current.preferences):
        raise api_error(
            status.HTTP_409_CONFLICT,
            "onboarding_incomplete",
            "Add your Gemini key, upload your resume and set your preferences first.",
        )
    if user.onboarded_at is None:
        user.onboarded_at = datetime.now(UTC)
        await session.commit()
    queued = None
    if body.start:
        queued = await enqueue("first_run", str(user.id), job_id=f"first_run:{user.id}") is not None
    return current.model_copy(update={"completed": True, "first_run_queued": queued})
