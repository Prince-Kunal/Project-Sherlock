from datetime import datetime

from pydantic import BaseModel


class KnownPersonOut(BaseModel):
    name: str
    position: str
    alumni: bool  # went to the user's college
    profile_url: str | None


class WarmPathOut(BaseModel):
    """People the user knows at a company (PLAN.md Phase 10). Shown as a hint; Sherlock never emails them."""

    count: int
    alumni: int
    people: list[KnownPersonOut]


class ConnectionsSummary(BaseModel):
    count: int
    companies: int
    alumni: int
    uploaded_at: datetime | None
