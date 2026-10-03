import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import UserOwnedBase, str_enum
from app.models.enums import (
    INACTIVE_OUTREACH_STATUSES,
    CampaignType,
    Outcome,
    OutreachEventType,
    OutreachStatus,
)

_inactive_sql = ", ".join(f"'{s.value}'" for s in INACTIVE_OUTREACH_STATUSES)


class Outreach(UserOwnedBase):
    """One outreach attempt (job-linked or open). `status` is changed only via services/email/state.py."""

    __tablename__ = "outreach"
    __table_args__ = (
        # Invariant 4: one active outreach per (user, company), across both modes.
        Index(
            "uq_outreach_one_active_per_company",
            "user_id",
            "company_id",
            unique=True,
            postgresql_where=text(f"status NOT IN ({_inactive_sql})"),
        ),
        CheckConstraint("campaign_type <> 'job' OR job_id IS NOT NULL", name="job_campaign_has_job"),
        CheckConstraint("followup_count BETWEEN 0 AND 1", name="followup_count_max_one"),
    )

    campaign_type: Mapped[CampaignType] = mapped_column(str_enum(CampaignType, "campaign_type"))
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="RESTRICT"), index=True)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    company_match_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("company_matches.id", ondelete="SET NULL"), index=True
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[OutreachStatus] = mapped_column(
        str_enum(OutreachStatus, "outreach_status"), server_default=OutreachStatus.DRAFTING.value, index=True
    )
    subject: Mapped[str | None] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text)
    tailored_resume: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    resume_pdf_path: Mapped[str | None] = mapped_column(Text)
    resume_diff: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    ats_keyword_coverage: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    personalization_source: Mapped[str | None] = mapped_column(Text)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    gmail_message_id: Mapped[str | None] = mapped_column(String(255))
    gmail_thread_id: Mapped[str | None] = mapped_column(String(255))
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    followup_count: Mapped[int] = mapped_column(Integer, server_default="0")
    outcome: Mapped[Outcome] = mapped_column(str_enum(Outcome, "outcome"), server_default=Outcome.NONE.value)
    notes: Mapped[str] = mapped_column(Text, server_default="")
    failure_reason: Mapped[str | None] = mapped_column(Text)


class OutreachEvent(UserOwnedBase):
    """Append-only audit log. Never update or delete rows (except via full user-data deletion)."""

    __tablename__ = "outreach_events"

    outreach_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outreach.id", ondelete="CASCADE"), index=True)
    type: Mapped[OutreachEventType] = mapped_column(str_enum(OutreachEventType, "outreach_event_type"))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
