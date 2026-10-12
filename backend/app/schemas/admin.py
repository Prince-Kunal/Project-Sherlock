import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.enums import SuppressionReason


class OperationUsage(BaseModel):
    provider: str
    operation: str
    units: int
    est_cost_usd: Decimal


class UserUsage(BaseModel):
    user_id: uuid.UUID
    email: str
    name: str
    is_admin: bool
    is_active: bool
    onboarded: bool
    joined_at: datetime
    llm_calls: int
    llm_usd: Decimal
    contact_lookups: int  # people searches (Hunter + Apollo), the monthly quota's unit
    contact_verifications: int
    est_cost_usd: Decimal  # every provider's estimated cost
    sent: int  # emails sent this month (first emails and follow-ups)
    quota_exceeded: list[str]


class UsageReport(BaseModel):
    month: str  # YYYY-MM
    since: datetime
    until: datetime
    contact_lookups_limit: int
    llm_usd_limit: Decimal
    users: list[UserUsage]
    operations: list[OperationUsage]  # every user together


class SuppressionOut(BaseModel):
    email: str
    reason: SuppressionReason
    created_at: datetime


class SuppressionIn(BaseModel):
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SuppressionPage(BaseModel):
    items: list[SuppressionOut]
    total: int
