from datetime import datetime

from pydantic import BaseModel, Field


class LLMKeyIn(BaseModel):
    api_key: str = Field(min_length=10, max_length=200)


class LLMKeyStatus(BaseModel):
    configured: bool
    provider: str | None = None
    verified_at: datetime | None = None
    owner_fallback_allowed: bool
    notice: str


class HunterKeyIn(BaseModel):
    api_key: str = Field(min_length=10, max_length=200)


class HunterKeyStatus(BaseModel):
    configured: bool
    verified_at: datetime | None
    owner_fallback_allowed: bool
    searches_this_month: int
    monthly_limit: int
