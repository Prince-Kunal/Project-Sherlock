"""phase 7: mark contacts made up by the fake provider

A new email source, fake, marks contacts invented by FakeContactProvider (USE_FAKES=true). The
sender refuses them when fakes are off: their addresses are made up but may use real company
domains.

Revision ID: c4e1f7a2b9d5
Revises: b7c2d4e9f013
Create Date: 2026-10-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c4e1f7a2b9d5"
down_revision: str | None = "b7c2d4e9f013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMAIL_SOURCES_OLD = ("hunter", "apollo", "manual", "pattern", "hn")
EMAIL_SOURCES_NEW = (*EMAIL_SOURCES_OLD, "fake")


def _swap(values: tuple[str, ...]) -> None:
    name = op.f("ck_contacts_email_source")
    op.drop_constraint(name, "contacts", type_="check")
    op.create_check_constraint(name, "contacts", "email_source IN (" + ", ".join(f"'{v}'" for v in values) + ")")


def upgrade() -> None:
    _swap(EMAIL_SOURCES_NEW)
    # Contacts the fake provider made before this marker existed: its four people, its fixed
    # confidence and a first-name address.
    op.execute(
        """
        UPDATE contacts SET email_source = 'fake'
        WHERE email_source = 'hunter' AND confidence = 90
          AND (full_name, title) IN (
            ('Asha Rao', 'Co-founder & CTO'), ('Vikram Iyer', 'Engineering Manager'),
            ('Neha Kapoor', 'Technical Recruiter'), ('Rahul Menon', 'Senior Software Engineer'))
          AND split_part(email, '@', 1) = lower(split_part(full_name, ' ', 1))
        """
    )


def downgrade() -> None:
    op.execute("UPDATE contacts SET email_source = 'hunter' WHERE email_source = 'fake'")
    _swap(EMAIL_SOURCES_OLD)
