import uuid
from datetime import datetime, time

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    false,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedBase, str_enum
from app.models.enums import LLMProvider, OAuthProvider


class User(TimestampedBase):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str] = mapped_column(String(200), server_default="")
    is_admin: Mapped[bool] = mapped_column(Boolean, server_default=false())
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true())
    timezone: Mapped[str] = mapped_column(String(64), server_default="Asia/Kolkata")


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
