"""`WithinQuota`: routes that would call the LLM or a contact provider refuse users over their monthly
quota (PLAN.md Phase 9) with `429 quota_exceeded`, so a button can't do what the daily jobs skip."""

from typing import Annotated

from fastapi import Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import api_error
from app.core.auth import CurrentUser
from app.core.db import get_session
from app.services.quotas import quota_status


async def require_quota(user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]) -> None:
    status_ = await quota_status(session, user.id)
    if status_.exceeded:
        raise api_error(status.HTTP_429_TOO_MANY_REQUESTS, "quota_exceeded", status_.message)


WithinQuota = Depends(require_quota)
