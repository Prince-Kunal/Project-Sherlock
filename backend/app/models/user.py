import uuid
from datetime import datetime, time

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    false,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedBase, UserOwnedBase, str_enum
from app.models.enums import LLMProvider, OAuthProvider, ServiceKeyType


class User(TimestampedBase):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str] = mapped_column(String(200), server_default="")
    is_admin: Mapped[bool] = mapped_column(Boolean, server_default=false())
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true())
    timezone: Mapped[str] = mapped_column(String(64), server_default="Asia/Kolkata")
    onboarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # finished /welcome


class AllowedEmail(TimestampedBase):
    __tablename__ = "allowed_emails"

    email: Mapped[str] = mapped_column(String(320), unique=True)


class UserPreferences(TimestampedBase):
    __tablename__ = "user_preferences"
    __table_args__ = (
        CheckConstraint("min_fit_score BETWEEN 0 AND 100", name="min_fit_score_range"),
        CheckConstraint("open_outreach_share BETWEEN 0 AND 100", name="open_outreach_share_range"),
        CheckConstraint("daily_send_cap BETWEEN 0 AND 30", name="daily_send_cap_range"),
        CheckConstraint("max_job_age_days > 0", name="max_job_age_days_positive"),
        CheckConstraint("daily_draft_batch >= 0", name="daily_draft_batch_nonneg"),
        CheckConstraint("followup_after_days > 0", name="followup_after_days_positive"),
        CheckConstraint("draft_style IN ('ab', 'a', 'b')", name="draft_style_values"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    target_roles: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    employment_types: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    locations: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    remote_ok: Mapped[bool] = mapped_column(Boolean, server_default=true())
    company_stages: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    min_fit_score: Mapped[int] = mapped_column(Integer, server_default="70")
    max_job_age_days: Mapped[int] = mapped_column(Integer, server_default="14")
    daily_draft_batch: Mapped[int] = mapped_column(Integer, server_default="8")
    open_outreach_share: Mapped[int] = mapped_column(Integer, server_default="40")
    daily_send_cap: Mapped[int] = mapped_column(Integer, server_default="15")
    followup_after_days: Mapped[int] = mapped_column(Integer, server_default="6")
    send_window_start: Mapped[time] = mapped_column(Time, server_default=text("'09:30'"))
    send_window_end: Mapped[time] = mapped_column(Time, server_default=text("'18:00'"))
    paused: Mapped[bool] = mapped_column(Boolean, server_default=false())
    about_me: Mapped[str] = mapped_column(String(300), server_default="")
    # Phase 10: which feeds supply this user's matches (JobFeed values), and the Monday summary email.
    job_sources: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{boards,adzuna,hn,remotive}")
    weekly_summary: Mapped[bool] = mapped_column(Boolean, server_default=true())
    draft_style: Mapped[str] = mapped_column(String(8), server_default="ab")  # A/B test, or lock "a"/"b"


class OAuthToken(TimestampedBase):
    __tablename__ = "oauth_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    provider: Mapped[OAuthProvider] = mapped_column(str_enum(OAuthProvider, "oauth_provider"))
    encrypted_refresh_token: Mapped[str] = mapped_column(Text)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    needs_reauth: Mapped[bool] = mapped_column(Boolean, server_default=false())


class UserLLMKey(TimestampedBase):
    __tablename__ = "user_llm_keys"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    provider: Mapped[LLMProvider] = mapped_column(str_enum(LLMProvider, "llm_provider"))
    encrypted_api_key: Mapped[str] = mapped_column(Text)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_quota_exhausted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserServiceKey(TimestampedBase):
    """A user's own key for a non-LLM service (Hunter), Fernet-encrypted (invariant 6)."""

    __tablename__ = "user_service_keys"
    __table_args__ = (UniqueConstraint("user_id", "service", name="uq_user_service_keys_user_service"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    service: Mapped[ServiceKeyType] = mapped_column(str_enum(ServiceKeyType, "service_key_type"))
    encrypted_api_key: Mapped[str] = mapped_column(Text)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quota_exhausted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserConnection(UserOwnedBase):
    """Someone the user knows, from their own LinkedIn connections export or a CSV they made (PLAN.md
    Phase 10, warm paths). Used only to flag companies where the user knows someone; never sent to the
    LLM and never emailed by Sherlock. `*_key` are normalised for matching."""

    __tablename__ = "user_connections"
    __table_args__ = (Index("ix_user_connections_user_company_key", "user_id", "company_key"),)

    full_name: Mapped[str] = mapped_column(String(300))
    company: Mapped[str] = mapped_column(String(300), server_default="")
    company_key: Mapped[str] = mapped_column(String(300), server_default="")
    position: Mapped[str] = mapped_column(String(300), server_default="")
    school: Mapped[str] = mapped_column(String(300), server_default="")
    school_key: Mapped[str] = mapped_column(String(300), server_default="")
    profile_url: Mapped[str | None] = mapped_column(Text)
