import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedBase, str_enum
from app.models.enums import EmailSource, RoleCategory, SuppressionReason, VerificationStatus


class Contact(TimestampedBase):
    """Shared across users. last_contacted_at drives the global 30-day cooldown (invariant 4)."""

    __tablename__ = "contacts"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    full_name: Mapped[str] = mapped_column(String(300))
    title: Mapped[str | None] = mapped_column(String(300))
    email: Mapped[str] = mapped_column(String(320), unique=True)
    email_source: Mapped[EmailSource] = mapped_column(str_enum(EmailSource, "email_source"))
    verification_status: Mapped[VerificationStatus] = mapped_column(
        str_enum(VerificationStatus, "verification_status"), server_default=VerificationStatus.UNKNOWN.value
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    role_category: Mapped[RoleCategory] = mapped_column(
        str_enum(RoleCategory, "role_category"), server_default=RoleCategory.OTHER.value
    )
    last_contacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # As reported by the provider; used by the selector (services/contacts/selector.py).
    seniority: Mapped[str | None] = mapped_column(String(50))
    department: Mapped[str | None] = mapped_column(String(100))
    confidence: Mapped[int | None] = mapped_column(Integer)


class SuppressionEntry(TimestampedBase):
    """Global do-not-contact list (invariants 3 and 9)."""

    __tablename__ = "suppression_list"

    email: Mapped[str] = mapped_column(String(320), unique=True)
    reason: Mapped[SuppressionReason] = mapped_column(str_enum(SuppressionReason, "suppression_reason"))
