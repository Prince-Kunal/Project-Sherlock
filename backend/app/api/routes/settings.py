import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import llm_errors
from app.core.auth import CurrentUser
from app.core.config import get_settings
from app.core.db import get_session
from app.schemas.settings import LLMKeyIn, LLMKeyStatus
from app.services.llm.client import LLMClient
from app.services.llm.user_keys import FREE_TIER_NOTICE, get_key_row, save_key
from app.services.registry import get_llm_client

router = APIRouter(prefix="/settings", tags=["settings"])

Session = Annotated[AsyncSession, Depends(get_session)]


async def _status(session: AsyncSession, user_id: uuid.UUID) -> LLMKeyStatus:
    row = await get_key_row(session, user_id)
    return LLMKeyStatus(
        configured=row is not None,
        provider=row.provider.value if row else None,
        verified_at=row.verified_at if row else None,
        owner_fallback_allowed=get_settings().allow_owner_key_fallback,
        notice=FREE_TIER_NOTICE,
    )


@router.get("/llm-key", response_model=LLMKeyStatus)
async def get_llm_key(user: CurrentUser, session: Session) -> LLMKeyStatus:
    """Key status only. The key itself is never returned."""
    return await _status(session, user.id)


@router.put("/llm-key", response_model=LLMKeyStatus)
async def put_llm_key(
    body: LLMKeyIn,
    user: CurrentUser,
    session: Session,
    llm: Annotated[LLMClient, Depends(get_llm_client)],
) -> LLMKeyStatus:
    api_key = body.api_key.strip()
    with llm_errors():
        await llm.verify_api_key(api_key)  # one tiny request; rejects bad keys before storing
    await save_key(session, user.id, api_key)
    await session.commit()
    return await _status(session, user.id)


@router.delete("/llm-key", status_code=status.HTTP_204_NO_CONTENT)
async def delete_llm_key(user: CurrentUser, session: Session) -> None:
    row = await get_key_row(session, user.id)
    if row is not None:
        await session.delete(row)
        await session.commit()
