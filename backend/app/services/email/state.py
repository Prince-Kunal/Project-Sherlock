"""The outreach state machine (PLAN.md §7). No other code sets `Outreach.status`.

    drafting ──► pending_review ──► approved ──► scheduled ──► sent ──► replied ──► closed
       │              │  ▲                            │          │
       │              │  └── (edit/regenerate)        │          └─► followup_due ─► pending_review
       │              └──► skipped                    └─► send_failed ─► pending_review
       └──► failed ──► drafting (retry once the cause is fixed, e.g. a contact added by hand)

`transition` validates the move and appends an `outreach_events` row in the same transaction.
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Outreach, OutreachEvent
from app.models.enums import OutreachEventType, OutreachStatus

S = OutreachStatus

ALLOWED: dict[OutreachStatus, set[OutreachStatus]] = {
    S.DRAFTING: {S.PENDING_REVIEW, S.FAILED},
    S.PENDING_REVIEW: {S.PENDING_REVIEW, S.APPROVED, S.SKIPPED, S.DRAFTING, S.FAILED},
    S.APPROVED: {S.SCHEDULED, S.PENDING_REVIEW},
    S.SCHEDULED: {S.SENT, S.SEND_FAILED},
    S.SEND_FAILED: {S.PENDING_REVIEW},
    S.SENT: {S.REPLIED, S.FOLLOWUP_DUE, S.CLOSED},
    S.FOLLOWUP_DUE: {S.PENDING_REVIEW, S.REPLIED, S.CLOSED},
    S.REPLIED: {S.CLOSED},
    S.FAILED: {S.DRAFTING},
    S.SKIPPED: set(),
    S.CLOSED: set(),
}

# The event a move records unless the caller names a more specific one (e.g. edited, regenerated).
DEFAULT_EVENT: dict[OutreachStatus, OutreachEventType] = {
    S.PENDING_REVIEW: OutreachEventType.DRAFTED,
    S.APPROVED: OutreachEventType.APPROVED,
    S.SKIPPED: OutreachEventType.SKIPPED,
    S.SCHEDULED: OutreachEventType.SCHEDULED,
    S.SENT: OutreachEventType.SENT,
    S.SEND_FAILED: OutreachEventType.SEND_FAILED,
    S.REPLIED: OutreachEventType.REPLY_DETECTED,
    S.CLOSED: OutreachEventType.CLOSED,
    S.FAILED: OutreachEventType.FAILED,
    S.DRAFTING: OutreachEventType.RETRIED,
    S.FOLLOWUP_DUE: OutreachEventType.FOLLOWUP_DRAFTED,
}


class InvalidTransitionError(Exception):
    def __init__(self, current: OutreachStatus, target: OutreachStatus) -> None:
        super().__init__(f"outreach can't move from {current.value} to {target.value}")
        self.current = current
        self.target = target


def can_transition(current: OutreachStatus, target: OutreachStatus) -> bool:
    return target in ALLOWED[current]


async def record_event(
    session: AsyncSession,
    outreach: Outreach,
    event: OutreachEventType,
    payload: dict[str, Any] | None = None,
) -> OutreachEvent:
    """Append an audit event without changing status (e.g. contact_changed). Caller commits."""
    row = OutreachEvent(outreach_id=outreach.id, user_id=outreach.user_id, type=event, payload=payload or {})
    session.add(row)
    await session.flush()
    return row


async def transition(
    session: AsyncSession,
    outreach: Outreach,
    target: OutreachStatus,
    *,
    actor_id: uuid.UUID | None,
    event: OutreachEventType | None = None,
    payload: dict[str, Any] | None = None,
    failure_reason: str | None = None,
) -> OutreachEvent:
    """Move `outreach` to `target` and record why. `actor_id` is the user who acted (None for the
    system). Moving to `failed` requires a reason; leaving it clears the reason. Caller commits."""
    if not can_transition(outreach.status, target):
        raise InvalidTransitionError(outreach.status, target)
    if target == S.FAILED and not failure_reason:
        raise ValueError("moving to failed needs a failure_reason")
    before = outreach.status
    outreach.status = target
    outreach.failure_reason = failure_reason if target == S.FAILED else None
    details = {"from": before.value, "to": target.value, "actor": str(actor_id) if actor_id else "system"}
    if failure_reason:
        details["reason"] = failure_reason
    return await record_event(
        session, outreach, event or DEFAULT_EVENT[target], {**details, **(payload or {})}
    )
