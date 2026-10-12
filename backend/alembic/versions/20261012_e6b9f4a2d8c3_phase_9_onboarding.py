"""phase 9: users.onboarded_at

Set when a user finishes (or skips) the onboarding flow; until then the app sends them to /welcome.
Everyone who already has an account was onboarded by hand, so existing rows get the migration time.

Revision ID: e6b9f4a2d8c3
Revises: d5a8e3f1c7b2
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e6b9f4a2d8c3"
down_revision: str | None = "d5a8e3f1c7b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("onboarded_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE users SET onboarded_at = now()")


def downgrade() -> None:
    op.drop_column("users", "onboarded_at")
