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


class GmailStatus(BaseModel):
    connected: bool  # authorised, with both Gmail permissions, and not expired
    email: str
    needs_reauth: bool  # Google expired or revoked the authorisation (every ~7 days in Testing mode)
    missing_permissions: bool  # signed in but the Gmail boxes were unticked on the consent screen
    connected_at: datetime | None
    paused: bool
    google_sign_in: bool  # whether this server has Google OAuth configured at all


class AllowedEmailIn(BaseModel):
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AllowedEmailOut(BaseModel):
    email: str
    created_at: datetime
    signed_up: bool
