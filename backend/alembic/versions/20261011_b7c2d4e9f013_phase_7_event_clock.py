"""phase 7: outreach event clock and the followup_due event type

outreach_events.created_at uses clock_timestamp(): events written in one transaction get distinct,
ordered times, so "approved after the last edit" is well defined at send time (invariant 1).
A new event type, followup_due, marks a sent email that waited long enough for a follow-up.

Revision ID: b7c2d4e9f013
Revises: 6ef45b1e7d85
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7c2d4e9f013"
down_revision: str | None = "6ef45b1e7d85"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EVENT_TYPES_OLD = (
    "drafted", "edited", "regenerated", "approved", "skipped", "scheduled", "sent", "send_failed",
    "reply_detected", "followup_drafted", "followup_sent", "bounced", "closed", "outcome_set",
    "upgraded_to_job", "failed", "retried", "contact_changed",
)  # fmt: skip
EVENT_TYPES_NEW = (*EVENT_TYPES_OLD, "followup_due")


def _swap_check(table: str, name: str, column: str, values: tuple[str, ...]) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(
        op.f(f"ck_{table}_{name}"), table, f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"
    )


def upgrade() -> None:
    op.alter_column("outreach_events", "created_at", server_default=sa.text("clock_timestamp()"))
    _swap_check("outreach_events", "outreach_event_type", "type", EVENT_TYPES_NEW)


def downgrade() -> None:
    _swap_check("outreach_events", "outreach_event_type", "type", EVENT_TYPES_OLD)
    op.alter_column("outreach_events", "created_at", server_default=sa.text("now()"))
