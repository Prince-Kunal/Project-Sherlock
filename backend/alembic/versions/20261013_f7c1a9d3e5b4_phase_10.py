"""phase 10: more job sources, per-user source choice, draft styles, weekly summary, connections

- companies.ats_type gains smartrecruiters / workable / recruitee; jobs.source also gains remotive.
- user_preferences.job_sources: which sources feed this user's matches (manual jobs always do).
- user_preferences.weekly_summary: the Monday summary email to yourself.
- user_preferences.draft_style: "ab" (test both styles) or lock to "a" / "b".
- outreach.draft_variant: the A/B draft style ('a' or 'b') the email was written in.
- user_connections: people the user knows (their own LinkedIn export or a CSV), for warm-path hints.

Revision ID: f7c1a9d3e5b4
Revises: e6b9f4a2d8c3
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f7c1a9d3e5b4"
down_revision: str | None = "e6b9f4a2d8c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ATS_OLD = ("greenhouse", "lever", "ashby", "none")
ATS_NEW = ("greenhouse", "lever", "ashby", "smartrecruiters", "workable", "recruitee", "none")
SOURCES_OLD = ("greenhouse", "lever", "ashby", "adzuna", "hn", "manual")
SOURCES_NEW = (*SOURCES_OLD, "smartrecruiters", "workable", "recruitee", "remotive")


def _swap_check(table: str, name: str, column: str, values: tuple[str, ...]) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(
        op.f(f"ck_{table}_{name}"), table, f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"
    )


def upgrade() -> None:
    _swap_check("companies", "ats_type", "ats_type", ATS_NEW)
    _swap_check("jobs", "job_source", "source", SOURCES_NEW)
    op.add_column(
        "user_preferences",
        sa.Column(
            "job_sources",
            postgresql.ARRAY(sa.Text()),
            server_default="{boards,adzuna,hn,remotive}",
            nullable=False,
        ),
    )
    op.add_column(
        "user_preferences",
        sa.Column("weekly_summary", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.add_column(
        "user_preferences",
        sa.Column("draft_style", sa.String(length=8), server_default="ab", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_user_preferences_draft_style_values"), "user_preferences", "draft_style IN ('ab', 'a', 'b')"
    )
    op.add_column("outreach", sa.Column("draft_variant", sa.String(length=8), nullable=True))
    op.create_check_constraint(
        op.f("ck_outreach_draft_variant_values"), "outreach", "draft_variant IN ('a', 'b')"
    )
    op.create_table(
        "user_connections",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("full_name", sa.String(length=300), nullable=False),
        sa.Column("company", sa.String(length=300), server_default="", nullable=False),
        sa.Column("company_key", sa.String(length=300), server_default="", nullable=False),
        sa.Column("position", sa.String(length=300), server_default="", nullable=False),
        sa.Column("school", sa.String(length=300), server_default="", nullable=False),
        sa.Column("school_key", sa.String(length=300), server_default="", nullable=False),
        sa.Column("profile_url", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_user_connections_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_connections")),
    )
    op.create_index(op.f("ix_user_connections_user_id"), "user_connections", ["user_id"])
    op.create_index("ix_user_connections_user_company_key", "user_connections", ["user_id", "company_key"])


def downgrade() -> None:
    op.drop_index("ix_user_connections_user_company_key", table_name="user_connections")
    op.drop_index(op.f("ix_user_connections_user_id"), table_name="user_connections")
    op.drop_table("user_connections")
    op.drop_constraint(op.f("ck_outreach_draft_variant_values"), "outreach", type_="check")
    op.drop_column("outreach", "draft_variant")
    op.drop_constraint(op.f("ck_user_preferences_draft_style_values"), "user_preferences", type_="check")
    op.drop_column("user_preferences", "draft_style")
    op.drop_column("user_preferences", "weekly_summary")
    op.drop_column("user_preferences", "job_sources")
    op.execute("DELETE FROM jobs WHERE source IN ('smartrecruiters', 'workable', 'recruitee', 'remotive')")
    op.execute("UPDATE companies SET ats_type = 'none' WHERE ats_type IN ('smartrecruiters', 'workable', 'recruitee')")
    _swap_check("jobs", "job_source", "source", SOURCES_OLD)
    _swap_check("companies", "ats_type", "ats_type", ATS_OLD)
