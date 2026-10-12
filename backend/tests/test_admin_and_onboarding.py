"""Admin page data (PLAN.md Phase 9: usage and costs per user, the suppression list) and the onboarding
flow for a new friend."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import create_session_token
from app.core.security import encrypt_secret
from app.models import OAuthToken, SuppressionEntry, UsageLedger, User, UserPreferences
from app.models.enums import OAuthProvider, OutreachEventType, SuppressionReason, UsageProvider
from app.services.email.state import record_event
from app.services.google.fake import FakeGoogleOAuth
from app.services.google.oauth import SCOPES
from app.services.quotas import month_start
from app.services.registry import get_google_oauth
from tests.matching_fixtures import fixture_resume
from tests.sending_fixtures import sendable, sender

# --- Usage report -----------------------------------------------------------------------------------


async def test_usage_report_per_user_and_operation(auth_client: AsyncClient, session: AsyncSession) -> None:
    friend = await sender(session, "friend@example.com")
    this_month = datetime.now(UTC)
    last_month = month_start(this_month) - timedelta(days=3)
    session.add_all(
        [
            UsageLedger(
                user_id=friend.id, provider=UsageProvider.GEMINI, operation="draft_email", units=3,
                est_cost_usd=Decimal("0.03"),
            ),
            UsageLedger(user_id=friend.id, provider=UsageProvider.GEMINI, operation="match_jobs", units=2),
            UsageLedger(user_id=friend.id, provider=UsageProvider.HUNTER, operation="hunter_search", units=4),
            UsageLedger(user_id=friend.id, provider=UsageProvider.APOLLO, operation="apollo_search", units=1),
            UsageLedger(user_id=friend.id, provider=UsageProvider.HUNTER, operation="hunter_verify", units=5),
            UsageLedger(
                user_id=friend.id, provider=UsageProvider.HUNTER, operation="hunter_search", units=30,
                created_at=last_month,
            ),
        ]
    )  # fmt: skip
    outreach = await sendable(session, friend)
    await record_event(session, outreach, OutreachEventType.SENT, {})
    await session.commit()

    report = (await auth_client.get("/admin/usage")).json()
    assert report["month"] == this_month.strftime("%Y-%m")
    row = next(u for u in report["users"] if u["email"] == "friend@example.com")
    assert row["llm_calls"] == 5
    assert Decimal(row["llm_usd"]) == Decimal("0.03")
    assert (row["contact_lookups"], row["contact_verifications"], row["sent"]) == (5, 5, 1)
    assert row["quota_exceeded"] == []
    me = next(u for u in report["users"] if u["email"] == "dev@sherlock.local")
    assert (me["llm_calls"], me["contact_lookups"], me["is_admin"]) == (0, 0, True)
    ops = {(o["provider"], o["operation"]): o["units"] for o in report["operations"]}
    assert ops[("hunter", "hunter_search")] == 4
    assert ops[("gemini", "draft_email")] == 3

    earlier = (await auth_client.get("/admin/usage", params={"month": last_month.strftime("%Y-%m")})).json()
    row = next(u for u in earlier["users"] if u["email"] == "friend@example.com")
    assert (row["contact_lookups"], row["llm_calls"]) == (30, 0)
    assert (await auth_client.get("/admin/usage", params={"month": "2026-13"})).status_code == 422


# --- Suppression list ------------------------------------------------------------------------------


async def test_suppression_list_view_search_and_manual_add(
    auth_client: AsyncClient, session: AsyncSession
) -> None:
    session.add_all(
        [
            SuppressionEntry(email="optout@corp.example", reason=SuppressionReason.OPT_OUT),
            SuppressionEntry(email="bounced@other.example", reason=SuppressionReason.BOUNCE),
        ]
    )
    await session.commit()
    page = (await auth_client.get("/admin/suppression")).json()
    assert page["total"] == 2
    assert {i["email"] for i in page["items"]} == {"optout@corp.example", "bounced@other.example"}

    added = await auth_client.post("/admin/suppression", json={"email": "Phoned@Corp.example"})
    assert added.status_code == 201
    assert added.json()["reason"] == "manual"
    again = await auth_client.post("/admin/suppression", json={"email": "optout@corp.example"})
    assert again.json()["reason"] == "opt_out"  # an existing entry keeps its reason
    found = (await auth_client.get("/admin/suppression", params={"q": "corp"})).json()
    assert [i["email"] for i in found["items"]] == ["phoned@corp.example", "optout@corp.example"]
    assert (await auth_client.post("/admin/suppression", json={"email": "not-an-email"})).status_code == 422


# --- Onboarding --------------------------------------------------------------------------------------


@pytest.fixture
async def new_friend(client: AsyncClient, session: AsyncSession) -> dict[str, str]:
    """A friend who just signed in for the first time: no keys, no resume, default preferences."""
    user = User(email="newfriend@example.com", name="New Friend")
    session.add(user)
    await session.flush()
    session.add(UserPreferences(user_id=user.id))
    await session.commit()
    return {"Authorization": f"Bearer {create_session_token(user.id)}", "id": str(user.id)}


def _queue(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, tuple[Any, ...], str | None]]:
    enqueued: list[tuple[str, tuple[Any, ...], str | None]] = []

    class Pool:
        async def enqueue_job(self, name: str, *args: Any, _job_id: str | None = None) -> object:
            enqueued.append((name, args, _job_id))
            return type("Job", (), {"job_id": _job_id})()

        async def aclose(self) -> None:
            return None

    async def fake_pool(*_: object, **__: object) -> Pool:
        return Pool()

    monkeypatch.setattr("app.workers.queue.create_pool", fake_pool)
    return enqueued


async def test_onboarding_walks_a_new_friend_to_the_first_run(
    client: AsyncClient,
    session: AsyncSession,
    new_friend: dict[str, str],
    fake_llm: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.main import app

    headers = {"Authorization": new_friend["Authorization"]}
    user_id = uuid.UUID(new_friend["id"])
    me = (await client.get("/auth/me", headers=headers)).json()
    assert me["onboarded"] is False
    status = (await client.get("/onboarding", headers=headers)).json()
    assert status == {
        "google_sign_in": False,
        "gmail": False,
        "llm_key": False,
        "hunter_key": False,
        "resume": False,
        "preferences": False,
        "completed": False,
        "first_run_queued": None,
    }
    # The first run needs a key, a resume and preferences.
    early = await client.post("/onboarding/complete", json={"start": True}, headers=headers)
    assert early.status_code == 409
    assert early.json()["detail"]["code"] == "onboarding_incomplete"

    # Connect Gmail (here: the tokens Google sign-in would have stored).
    session.add(
        OAuthToken(
            user_id=user_id,
            provider=OAuthProvider.GOOGLE,
            encrypted_refresh_token=encrypt_secret("refresh-new"),
            scopes=list(SCOPES),
        )
    )
    await session.commit()
    app.dependency_overrides[get_google_oauth] = FakeGoogleOAuth
    try:
        status = (await client.get("/onboarding", headers=headers)).json()
    finally:
        app.dependency_overrides.pop(get_google_oauth, None)
    assert (status["google_sign_in"], status["gmail"]) == (True, True)

    # Keys, resume (as saved after reviewing the parsed one) and preferences.
    key = await client.put("/settings/llm-key", json={"api_key": "AIza-friend-key-123456"}, headers=headers)
    assert key.status_code == 200
    resume = await client.put("/resume", json=fixture_resume().model_dump(mode="json"), headers=headers)
    assert resume.status_code == 200, resume.text
    prefs = (await client.get("/preferences", headers=headers)).json()
    saved = await client.put(
        "/preferences",
        json={**prefs, "target_roles": ["Backend Intern"], "employment_types": ["internship"]},
        headers=headers,
    )
    assert saved.status_code == 200
    status = (await client.get("/onboarding", headers=headers)).json()
    assert (status["llm_key"], status["resume"], status["preferences"], status["completed"]) == (
        True,
        True,
        True,
        False,
    )

    enqueued = _queue(monkeypatch)
    done = await client.post("/onboarding/complete", json={"start": True}, headers=headers)
    assert done.status_code == 200
    assert (done.json()["completed"], done.json()["first_run_queued"]) == (True, True)
    assert enqueued == [("first_run", (str(user_id),), f"first_run:{user_id}")]
    assert (await client.get("/auth/me", headers=headers)).json()["onboarded"] is True


async def test_finishing_later_skips_the_first_run(
    client: AsyncClient, new_friend: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = {"Authorization": new_friend["Authorization"]}
    enqueued = _queue(monkeypatch)
    done = await client.post("/onboarding/complete", json={"start": False}, headers=headers)
    assert done.status_code == 200
    assert done.json()["completed"] is True
    assert enqueued == []
    assert (await client.get("/auth/me", headers=headers)).json()["onboarded"] is True


async def test_first_run_scores_jobs_then_builds_drafts(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.workers import settings as worker

    calls: list[str] = []

    async def match(ctx: dict[str, Any], user_id: str | None = None) -> dict[str, int]:
        calls.append(f"match:{user_id}")
        return {"users": 1, "scored": 7, "llm_calls": 1}

    async def build(ctx: dict[str, Any], user_id: str | None = None) -> dict[str, int]:
        calls.append(f"build:{user_id}")
        return {"users": 1, "drafted": 3, "failed": 0, "stopped": 0}

    monkeypatch.setattr(worker, "match_jobs_for_users", match)
    monkeypatch.setattr(worker, "build_daily_drafts", build)
    assert await worker.first_run({}, "u1") == {"scored": 7, "drafted": 3}
    assert calls == ["match:u1", "build:u1"]
    assert "first_run" in {
        getattr(f, "name", getattr(f, "__name__", "")) for f in worker.WorkerSettings.functions
    }
