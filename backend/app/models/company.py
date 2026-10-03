import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    true,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedBase, UserOwnedBase, str_enum
from app.models.enums import AtsType, CompanyMatchStatus, SizeHint

EMBEDDING_DIM = 384  # BAAI/bge-small-en-v1.5


class Company(TimestampedBase):
    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(String(300))
    domain: Mapped[str | None] = mapped_column(String(255), unique=True)
    ats_type: Mapped[AtsType] = mapped_column(
        str_enum(AtsType, "ats_type"), server_default=AtsType.NONE.value
    )
    ats_token: Mapped[str | None] = mapped_column(String(255))
    size_hint: Mapped[SizeHint] = mapped_column(
        str_enum(SizeHint, "size_hint"), server_default=SizeHint.UNKNOWN.value
    )
    employee_count: Mapped[int | None] = mapped_column(Integer)
    industry: Mapped[str | None] = mapped_column(String(200))
    hq_location: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    website_text: Mapped[str | None] = mapped_column(Text)
    website_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserCompanyBlock(UserOwnedBase):
    __tablename__ = "user_company_blocks"
    __table_args__ = (UniqueConstraint("user_id", "company_id", name="uq_user_company_blocks_user_company"),)

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)


class ProspectTarget(UserOwnedBase):
    """An open-outreach target profile (PLAN.md §1 'Open outreach'). A user may have several."""

    __tablename__ = "prospect_targets"

    name: Mapped[str] = mapped_column(String(200))
    contact_titles: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    industries: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    locations: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    company_sizes: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    include_companies: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), server_default="{}")
    exclude_companies: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), server_default="{}")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true())


class CompanyMatch(UserOwnedBase):
    __tablename__ = "company_matches"
    __table_args__ = (
        UniqueConstraint("user_id", "company_id", name="uq_company_matches_user_company"),
        CheckConstraint("score BETWEEN 0 AND 100", name="score_range"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    prospect_target_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prospect_targets.id", ondelete="SET NULL"), index=True
    )
    score: Mapped[int] = mapped_column(Integer)
    reasoning: Mapped[str] = mapped_column(Text, server_default="")
    status: Mapped[CompanyMatchStatus] = mapped_column(
        str_enum(CompanyMatchStatus, "company_match_status"), server_default=CompanyMatchStatus.NEW.value
    )
