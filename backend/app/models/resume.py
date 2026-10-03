from typing import Any

from sqlalchemy import Boolean, Index, Integer, Text, UniqueConstraint, false, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import UserOwnedBase


class MasterResume(UserOwnedBase):
    """One row per saved version; the newest has is_current = true. History is kept."""

    __tablename__ = "master_resumes"
    __table_args__ = (
        UniqueConstraint("user_id", "version", name="uq_master_resumes_user_version"),
        Index(
            "uq_master_resumes_one_current",
            "user_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
    )

    version: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    is_current: Mapped[bool] = mapped_column(Boolean, server_default=false())
    source_file_path: Mapped[str | None] = mapped_column(Text)
