from typing import Any

import pytest
from httpx import AsyncClient


async def test_defaults_match_plan(auth_client: AsyncClient) -> None:
    prefs = (await auth_client.get("/preferences")).json()
    assert prefs["min_fit_score"] == 70
    assert prefs["max_job_age_days"] == 14
    assert prefs["daily_draft_batch"] == 8
    assert prefs["open_outreach_share"] == 40
    assert prefs["daily_send_cap"] == 15
    assert prefs["followup_after_days"] == 6
    assert prefs["send_window_start"] == "09:30:00"
    assert prefs["send_window_end"] == "18:00:00"
    assert prefs["timezone"] == "Asia/Kolkata"
    assert prefs["paused"] is False


async def test_put_and_get_round_trip(auth_client: AsyncClient) -> None:
    prefs = (await auth_client.get("/preferences")).json()
    prefs |= {
        "target_roles": ["Backend Engineer Intern", "SDE Intern"],
        "employment_types": ["internship"],
        "locations": ["Bengaluru", "Remote"],
        "company_stages": ["startup", "mid"],
        "daily_send_cap": 30,
        "send_window_start": "10:00",
        "about_me": "Second-year CS student who likes backend systems.",
        "timezone": "Asia/Dubai",
    }
    response = await auth_client.put("/preferences", json=prefs)
    assert response.status_code == 200, response.text
    again = (await auth_client.get("/preferences")).json()
    assert again["target_roles"] == ["Backend Engineer Intern", "SDE Intern"]
    assert again["daily_send_cap"] == 30
    assert again["send_window_start"] == "10:00:00"
    assert again["timezone"] == "Asia/Dubai"


@pytest.mark.parametrize(
    "change",
    [
        {"daily_send_cap": 31},  # hard max 30
        {"min_fit_score": 101},
        {"open_outreach_share": -1},
        {"employment_types": ["contract"]},
        {"company_stages": ["enterprise"]},
        {"about_me": "x" * 301},
        {"send_window_start": "19:00", "send_window_end": "18:00"},
        {"timezone": "Mars/Olympus"},
        {"unknown_field": 1},
    ],
)
async def test_invalid_preferences_rejected(auth_client: AsyncClient, change: dict[str, Any]) -> None:
    prefs = (await auth_client.get("/preferences")).json() | change
    response = await auth_client.put("/preferences", json=prefs)
    assert response.status_code == 422


async def test_preferences_are_per_user(auth_client: AsyncClient, other_user_headers: dict[str, str]) -> None:
    prefs = (await auth_client.get("/preferences")).json() | {"daily_send_cap": 3}
    await auth_client.put("/preferences", json=prefs)
    auth_client.cookies.clear()
    other = (await auth_client.get("/preferences", headers=other_user_headers)).json()
    assert other["daily_send_cap"] == 15
