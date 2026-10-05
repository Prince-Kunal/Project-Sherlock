"""usage_ledger writes and reads (PLAN.md §13): every LLM call made for a user is logged."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import UsageLedger
from app.models.enums import UsageProvider
from app.services.llm.client import CallMeter, metered


async def record_llm_usage(session: AsyncSession, user_id: uuid.UUID, operation: str, calls: int) -> None:
    """Add a ledger row for `calls` provider requests (nothing for 0, e.g. all cache hits). Caller commits."""
    if calls <= 0:
        return
    session.add(
        UsageLedger(
            user_id=user_id,
            provider=UsageProvider(get_settings().llm_provider),
            operation=operation,
            units=calls,
        )
    )


async def llm_calls_since(session: AsyncSession, user_id: uuid.UUID, operation: str, since: datetime) -> int:
    total = await session.scalar(
        select(func.coalesce(func.sum(UsageLedger.units), 0)).where(
            UsageLedger.user_id == user_id,
            UsageLedger.operation == operation,
            UsageLedger.created_at >= since,
        )
    )
    return int(total or 0)


@asynccontextmanager
async def logged_llm_usage(
    session: AsyncSession, user_id: uuid.UUID, operation: str
) -> AsyncIterator[CallMeter]:
    """Count the LLM calls made inside the block and commit a ledger row, also when the block fails
    (the requests still used the user's quota). Use where nothing else is pending in `session`."""
    with metered() as meter:
        try:
            yield meter
        finally:
            if meter.calls:
                await record_llm_usage(session, user_id, operation, meter.calls)
                await session.commit()
