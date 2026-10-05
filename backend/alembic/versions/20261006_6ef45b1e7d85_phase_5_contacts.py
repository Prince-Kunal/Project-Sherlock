"""phase 5 contacts

Revision ID: 6ef45b1e7d85
Revises: a1447d61a96d
Create Date: 2026-10-06 03:43:59.827416
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "6ef45b1e7d85"
down_revision: str | None = "a1447d61a96d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMAIL_SOURCES_OLD = ("hunter", "apollo", "manual", "pattern")
EMAIL_SOURCES_NEW = (*EMAIL_SOURCES_OLD, "hn")
EVENT_TYPES_OLD = (
    "drafted", "edited", "regenerated", "approved", "skipped", "scheduled", "sent", "send_failed",
    "reply_detected", "followup_drafted", "followup_sent", "bounced", "closed", "outcome_set",
    "upgraded_to_job",
)  # fmt: skip
EVENT_TYPES_NEW = (*EVENT_TYPES_OLD, "failed", "retried", "contact_changed")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _swap_check(table: str, name: str, column: str, values: tuple[str, ...]) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, _in(column, values))


def upgrade() -> None:
    op.create_table(
        "user_service_keys",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "service",
            sa.Enum("hunter", "apollo", name="service_key_type", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("encrypted_api_key", sa.Text(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("quota_exhausted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "service IN ('hunter', 'apollo')", name=op.f("ck_user_service_keys_service_key_type")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_user_service_keys_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_service_keys")),
        sa.UniqueConstraint("user_id", "service", name="uq_user_service_keys_user_service"),
    )
    op.create_index(op.f("ix_user_service_keys_user_id"), "user_service_keys", ["user_id"], unique=False)
    op.add_column("companies", sa.Column("contacts_fetched_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("contacts", sa.Column("seniority", sa.String(length=50), nullable=True))
    op.add_column("contacts", sa.Column("department", sa.String(length=100), nullable=True))
    op.add_column("contacts", sa.Column("confidence", sa.Integer(), nullable=True))
    _swap_check("contacts", "email_source", "email_source", EMAIL_SOURCES_NEW)
    _swap_check("outreach_events", "outreach_event_type", "type", EVENT_TYPES_NEW)


def downgrade() -> None:
    _swap_check("outreach_events", "outreach_event_type", "type", EVENT_TYPES_OLD)
    _swap_check("contacts", "email_source", "email_source", EMAIL_SOURCES_OLD)
    op.drop_column("contacts", "confidence")
    op.drop_column("contacts", "department")
    op.drop_column("contacts", "seniority")
    op.drop_column("companies", "contacts_fetched_at")
    op.drop_index(op.f("ix_user_service_keys_user_id"), table_name="user_service_keys")
    op.drop_table("user_service_keys")
