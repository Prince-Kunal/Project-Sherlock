from decimal import Decimal

from sqlalchemy import Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import UserOwnedBase, str_enum
from app.models.enums import UsageProvider


class UsageLedger(UserOwnedBase):
    __tablename__ = "usage_ledger"

    provider: Mapped[UsageProvider] = mapped_column(str_enum(UsageProvider, "usage_provider"))
    operation: Mapped[str] = mapped_column(String(100))
    units: Mapped[int] = mapped_column(Integer, server_default="1")
    est_cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), server_default="0")
