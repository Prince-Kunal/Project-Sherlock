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
