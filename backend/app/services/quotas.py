"""Per-user monthly quotas (PLAN.md Phase 9), read from usage_ledger.

Two limits per calendar month (UTC): people searches at contact providers
(`MAX_CONTACT_LOOKUPS_PER_USER_MONTH`, Hunter + Apollo) and the estimated LLM spend
(`MAX_LLM_USD_PER_USER_MONTH`, `est_cost_usd` of the user's LLM rows). A user over either one is
skipped by every background job that would call a provider or the LLM for them, and the API refuses
the buttons that would (`quota_exceeded`). Nothing else stops: sending already-approved email and
watching for replies still run.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import UsageLedger
from app.models.enums import UsageProvider

LLM_PROVIDERS = (UsageProvider.GEMINI, UsageProvider.ANTHROPIC)
# Every provider's people searches count toward MAX_CONTACT_LOOKUPS_PER_USER_MONTH.
LOOKUP_OPERATIONS = ("hunter_search", "apollo_search")


def month_start(now: datetime) -> datetime:
    return now.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


class QuotaExceededError(Exception):
    def __init__(self, status: "QuotaStatus") -> None:
        super().__init__(", ".join(status.exceeded))
        self.status = status


@dataclass(frozen=True)
class QuotaStatus:
    contact_lookups: int
    contact_lookups_limit: int
    llm_usd: Decimal
    llm_usd_limit: Decimal
    resets_at: datetime

    @property
    def exceeded(self) -> list[str]:
        over = []
        if self.contact_lookups >= self.contact_lookups_limit:
            over.append("contact_lookups")
        if self.llm_usd > 0 and self.llm_usd >= self.llm_usd_limit:  # free-tier calls cost nothing
            over.append("llm_usd")
        return over

    @property
    def message(self) -> str:
        parts = []
        if "contact_lookups" in self.exceeded:
            parts.append(f"all {self.contact_lookups_limit} contact lookups")
        if "llm_usd" in self.exceeded:
            parts.append(f"the ${self.llm_usd_limit} AI budget")
        if not parts:
            return ""
        return (
            f"You've used {' and '.join(parts)} for this month, so Sherlock won't draft, match or look "
            f"anyone up for you until {self.resets_at:%-d %B}. Approved emails still go out."
        )


def _next_month(now: datetime) -> datetime:
    start = month_start(now)
    if start.month == 12:
        return start.replace(year=start.year + 1, month=1)
    return start.replace(month=start.month + 1)


async def contact_lookups_this_month(session: AsyncSession, user_id: uuid.UUID, now: datetime) -> int:
    total = await session.scalar(
        select(func.coalesce(func.sum(UsageLedger.units), 0)).where(
            UsageLedger.user_id == user_id,
            UsageLedger.operation.in_(LOOKUP_OPERATIONS),
            UsageLedger.created_at >= month_start(now),
        )
    )
    return int(total or 0)


async def llm_usd_this_month(session: AsyncSession, user_id: uuid.UUID, now: datetime) -> Decimal:
    total = await session.scalar(
        select(func.coalesce(func.sum(UsageLedger.est_cost_usd), 0)).where(
            UsageLedger.user_id == user_id,
            UsageLedger.provider.in_(LLM_PROVIDERS),
            UsageLedger.created_at >= month_start(now),
        )
    )
    return Decimal(total or 0)


async def quota_status(session: AsyncSession, user_id: uuid.UUID, now: datetime | None = None) -> QuotaStatus:
    now = now or datetime.now(UTC)
    settings = get_settings()
    return QuotaStatus(
        contact_lookups=await contact_lookups_this_month(session, user_id, now),
        contact_lookups_limit=settings.max_contact_lookups_per_user_month,
        llm_usd=await llm_usd_this_month(session, user_id, now),
        llm_usd_limit=Decimal(str(settings.max_llm_usd_per_user_month)),
        resets_at=_next_month(now),
    )


async def ensure_within_quota(session: AsyncSession, user_id: uuid.UUID, now: datetime | None = None) -> None:
    """Raise QuotaExceededError when the user is over a monthly limit."""
    status = await quota_status(session, user_id, now)
    if status.exceeded:
        raise QuotaExceededError(status)


async def over_quota(session: AsyncSession, user_id: uuid.UUID, now: datetime | None = None) -> bool:
    return bool((await quota_status(session, user_id, now)).exceeded)
