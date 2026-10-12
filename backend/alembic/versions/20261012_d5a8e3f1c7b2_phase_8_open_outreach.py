"""phase 8: open outreach (prospecting)

The tables (prospect_targets, company_matches) and the outreach columns (campaign_type, company_id,
company_match_id, nullable job_id with its CHECK) were created in the initial schema, and every
outreach row so far is `job`. This adds what open outreach needs on top:

- companies.industry_tags / locations: the company directory's industries and tags, and every place
  it lists (offices plus regions such as "Remote"), for the target filters.
- company_matches.angle / embedding_score: the CompanyMatchResult angle and the prefilter similarity.
- prospect_targets.target_roles: the roles the user wants at those companies (the "synthetic brief"
  for tailoring an open-outreach resume).

Revision ID: d5a8e3f1c7b2
Revises: c4e1f7a2b9d5
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d5a8e3f1c7b2"
down_revision: str | None = "c4e1f7a2b9d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _text_array(name: str) -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(name, sa.ARRAY(sa.Text()), server_default="{}", nullable=False)


def upgrade() -> None:
    op.add_column("companies", _text_array("industry_tags"))
    op.add_column("companies", _text_array("locations"))
    op.add_column("company_matches", sa.Column("angle", sa.Text(), server_default="", nullable=False))
    op.add_column("company_matches", sa.Column("embedding_score", sa.Float(), nullable=True))
    op.add_column("prospect_targets", _text_array("target_roles"))


def downgrade() -> None:
    op.drop_column("prospect_targets", "target_roles")
    op.drop_column("company_matches", "embedding_score")
    op.drop_column("company_matches", "angle")
    op.drop_column("companies", "locations")
    op.drop_column("companies", "industry_tags")
