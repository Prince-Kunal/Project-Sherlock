from datetime import time
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class PreferencesBase(BaseModel):
    target_roles: list[ShortText] = Field(default_factory=list, max_length=20)
    employment_types: list[Literal["internship", "full_time"]] = Field(default_factory=list)
    locations: list[ShortText] = Field(default_factory=list, max_length=20)
    remote_ok: bool = True
    company_stages: list[Literal["startup", "mid", "large"]] = Field(default_factory=list)
    min_fit_score: int = Field(70, ge=0, le=100)
    max_job_age_days: int = Field(14, ge=1, le=60)
    daily_draft_batch: int = Field(8, ge=0, le=30)
    open_outreach_share: int = Field(40, ge=0, le=100)
    daily_send_cap: int = Field(15, ge=0, le=30)  # hard max 30 (PLAN.md §5)
    followup_after_days: int = Field(6, ge=1, le=30)
    send_window_start: time = time(9, 30)
    send_window_end: time = time(18, 0)
    paused: bool = False
    about_me: str = Field("", max_length=300)
    timezone: str = "Asia/Kolkata"

    @field_validator("timezone")
    @classmethod
    def _valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown timezone {value!r}") from exc
        return value

    @model_validator(mode="after")
    def _window_order(self) -> "PreferencesBase":
        if self.send_window_start >= self.send_window_end:
            raise ValueError("send_window_start must be before send_window_end")
        return self


class PreferencesIn(PreferencesBase):
    model_config = ConfigDict(extra="forbid")


class PreferencesOut(PreferencesBase):
    pass
