import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedBase, UserOwnedBase, str_enum
from app.models.company import EMBEDDING_DIM
from app.models.enums import JobMatchStatus, JobSourceType


class Job(TimestampedBase):
    """A posting. dedupe_hash = sha256(norm(company domain or name) + norm(title) + norm(location)).
    Effective age = posted_at if present, else first_seen_at."""

    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_source_external_id", "source", "external_id"),
        # The feed filters and sorts by effective date = posted_at if known, else first_seen_at.
        Index(
            "ix_jobs_active_effective_date",
            "is_active",
            func.coalesce(text("posted_at"), text("first_seen_at")),
        ),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    source: Mapped[JobSourceType] = mapped_column(str_enum(JobSourceType, "job_source"))
    external_id: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(300))
    location: Mapped[str | None] = mapped_column(String(300))
    remote: Mapped[bool | None] = mapped_column(Boolean)
    employment_type: Mapped[str | None] = mapped_column(String(32))
    description_text: Mapped[str] = mapped_column(Text, server_default="")
    url: Mapped[str | None] = mapped_column(Text)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    missed_polls: Mapped[int] = mapped_column(Integer, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true())
    dedupe_hash: Mapped[str] = mapped_column(String(64), unique=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    # Source extras, e.g. HN contact hints for Phase 5 ({"contact_emails": [...], "hn_comment_id": ...}).
    source_meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class JobMatch(UserOwnedBase):
    __tablename__ = "job_matches"
    __table_args__ = (
        UniqueConstraint("user_id", "job_id", name="uq_job_matches_user_job"),
        CheckConstraint("llm_score IS NULL OR llm_score BETWEEN 0 AND 100", name="llm_score_range"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    embedding_score: Mapped[float | None] = mapped_column(Float)
    llm_score: Mapped[int | None] = mapped_column(Integer)
    matched_skills: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    missing_skills: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    reasoning: Mapped[str] = mapped_column(Text, server_default="")
    status: Mapped[JobMatchStatus] = mapped_column(
        str_enum(JobMatchStatus, "job_match_status"), server_default=JobMatchStatus.NEW.value
    )
