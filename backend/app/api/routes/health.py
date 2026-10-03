import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.redis import get_redis

router = APIRouter(tags=["health"])
log = logging.getLogger(__name__)

Check = Literal["ok", "error"]


class HealthOut(BaseModel):
    status: Check
    db: Check
    redis: Check


@router.get("/health", response_model=HealthOut)
async def health(
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> HealthOut:
    db: Check = "ok"
    cache: Check = "ok"
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        log.exception("health: database check failed")
        db = "error"
    try:
        await redis.ping()
    except Exception:
        log.exception("health: redis check failed")
        cache = "error"
    overall: Check = "ok" if db == cache == "ok" else "error"
    if overall != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthOut(status=overall, db=db, redis=cache)
