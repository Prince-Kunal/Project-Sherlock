"""Per-user monthly quotas (PLAN.md Phase 9): over a limit, no provider or LLM call is made for that
user, by any background job or button, and the user is told why."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.redis import get_redis
from app.models import Outreach, UsageLedger, User
from app.models.enums import OutreachStatus, UsageProvider
from app.services.contacts.fake import FakeContactProvider
from app.services.email.followups import Followups
from app.services.email.pipeline import DraftPipeline
from app.services.email.replies import ReplyChecker
from app.services.embeddings.fake import FakeEmbedder
from app.services.llm.fake import FakeLLMClient
from app.services.matching.pipeline import Matcher
from app.services.quotas import QuotaExceededError, ensure_within_quota, month_start, quota_status
from app.services.registry import build_fake_llm_client
from app.services.usage import record_llm_usage
from tests.matching_fixtures import seed_fixture_jobs, seed_matching_user
from tests.sending_fixtures import mailbox_factory, sendable, sender
from tests.test_prospects import (
    _company_matcher,
    _company_matches,
    _drafting_user,
    _job_matches,
    _matcher_user,
)

NOW = datetime.now(UTC)


async def _use(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    lookups: int = 0,
    llm_usd: str = "0",
    at: datetime | None = None,
) -> None:
    """Ledger rows as if the user had already spent this much this month (or at `at`)."""
    rows = []
    if lookups:
        rows.append(
            UsageLedger(
                user_id=user_id, provider=UsageProvider.HUNTER, operation="hunter_search", units=lookups
            )
        )
    if Decimal(llm_usd):
        rows.append(
            UsageLedger(
                user_id=user_id,
                provider=UsageProvider.GEMINI,
                operation="draft_email",
                units=1,
                est_cost_usd=Decimal(llm_usd),
            )
        )
    for row in rows:
        if at is not None:
            row.created_at = at
        session.add(row)
    await session.commit()


LIMIT = get_settings().max_contact_lookups_per_user_month


# --- Counting ---------------------------------------------------------------------------------------


async def test_status_counts_this_month_only(session: AsyncSession) -> None:
    user = await sender(session)
    last_month = month_start(NOW) - timedelta(days=2)
    await _use(session, user.id, lookups=LIMIT, llm_usd="9", at=last_month)
    await _use(session, user.id, lookups=3, llm_usd="0.25")
    status = await quota_status(session, user.id, NOW)
    assert (status.contact_lookups, status.llm_usd, status.exceeded) == (3, Decimal("0.25"), [])
    assert status.resets_at == (month_start(NOW) + timedelta(days=32)).replace(day=1)
    await ensure_within_quota(session, user.id, NOW)


async def test_each_limit_is_reported_with_a_notice(session: AsyncSession) -> None:
    user = await sender(session)
    await _use(session, user.id, lookups=LIMIT)
    status = await quota_status(session, user.id, NOW)
    assert status.exceeded == ["contact_lookups"]
    assert f"all {LIMIT} contact lookups" in status.message
    assert "Approved emails still go out" in status.message
    await _use(session, user.id, llm_usd=str(get_settings().max_llm_usd_per_user_month))
    status = await quota_status(session, user.id, NOW)
    assert status.exceeded == ["contact_lookups", "llm_usd"]
    with pytest.raises(QuotaExceededError):
        await ensure_within_quota(session, user.id, NOW)


async def test_free_tier_calls_never_exhaust_a_zero_budget(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "max_llm_usd_per_user_month", 0.0)
    user = await sender(session)
    await record_llm_usage(session, user.id, "draft_email", 30)  # LLM_USD_PER_CALL defaults to 0
    await session.commit()
    assert (await quota_status(session, user.id)).exceeded == []


async def test_llm_calls_are_costed_per_request(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "llm_usd_per_call", 0.0125)
    user = await sender(session)
    await record_llm_usage(session, user.id, "tailor_resume", 4)
    await session.commit()
    row = await session.scalar(select(UsageLedger).where(UsageLedger.user_id == user.id))
    assert row is not None
    assert row.est_cost_usd == Decimal("0.05")
    assert (await quota_status(session, user.id)).llm_usd == Decimal("0.05")


# --- Background jobs make no calls for a user over quota --------------------------------------------


@pytest.mark.parametrize("over", ["contact_lookups", "llm_usd"])
async def test_build_daily_drafts_skips_a_user_over_quota(session: AsyncSession, over: str) -> None:
    user = await _drafting_user(session, batch=4)
    await _job_matches(session, user, 2)
    await _company_matches(session, user, 2)
    if over == "contact_lookups":
        await _use(session, user.id, lookups=LIMIT)
    else:
        await _use(session, user.id, llm_usd="5")
    llm, contacts = build_fake_llm_client(), FakeContactProvider()
    summary = await DraftPipeline(llm, lambda _key: contacts).build_for_user(session, user.id)

    assert summary.stopped == "quota_exceeded"
    assert (summary.drafted, summary.failed) == (0, 0)
    assert llm.calls == []
    assert contacts.calls == []
    assert (await session.scalars(select(Outreach).where(Outreach.user_id == user.id))).all() == []


async def test_build_all_skips_only_the_user_over_quota(session: AsyncSession) -> None:
    from app.core.db import get_sessionmaker

    over = await _drafting_user(session, batch=1)
    await _job_matches(session, over, 1)
    await _use(session, over.id, lookups=LIMIT)
    llm, contacts = build_fake_llm_client(), FakeContactProvider()
    run = await DraftPipeline(llm, lambda _key: contacts).build_all(get_sessionmaker(), [over.id])
    assert run.stopped == {str(over.id): "quota_exceeded"}
    assert llm.calls == []
    assert contacts.calls == []


async def test_job_matching_skips_a_user_over_quota(session: AsyncSession) -> None:
    user = await seed_matching_user(session)
    await seed_fixture_jobs(session)
    await _use(session, user.id, llm_usd="7.5")
    llm = FakeLLMClient()
    settings = get_settings().model_copy(update={"embed_min_sim": 0.0})
    matcher = Matcher(llm=llm, embedder=FakeEmbedder(), redis=get_redis(), settings=settings)
    summary = await matcher.match_user(session, user.id)
    assert summary.candidates > 0
    assert summary.stopped == "quota_exceeded"
    assert llm.calls == []


async def test_company_matching_skips_a_user_over_quota(session: AsyncSession) -> None:
    user, _ = await _matcher_user(session)
    await _use(session, user.id, lookups=LIMIT)
    llm = FakeLLMClient()
    summary = await _company_matcher(llm).match_user(session, user.id)
    assert summary.stopped == "quota_exceeded"
    assert llm.calls == []


async def test_followups_skip_a_user_over_quota(session: AsyncSession) -> None:
    user = await sender(session)
    outreach = await sendable(session, user, approve=False)
    await session.execute(
        update(Outreach)
        .where(Outreach.id == outreach.id)
        .values(status=OutreachStatus.SENT, sent_at=NOW - timedelta(days=10))
    )
    await session.commit()
    await _use(session, user.id, lookups=LIMIT)
    llm = FakeLLMClient()
    summary = await Followups(llm).run_for_user(session, user.id, NOW)
    assert summary.stopped == "quota_exceeded"
    assert llm.calls == []
    await session.refresh(outreach)
    assert outreach.status == OutreachStatus.SENT


async def test_an_ambiguous_reply_is_not_sent_to_the_llm_over_quota(session: AsyncSession) -> None:
    user = await sender(session)
    await _use(session, user.id, llm_usd="5")
    llm = FakeLLMClient()
    checker = ReplyChecker(mailbox_factory(None), llm)  # type: ignore[arg-type]
    assert await checker._tiebreak(session, user.id, "No thanks for now.") == "opt_out"
    assert llm.calls == []


# --- Buttons refuse, and the user sees why ----------------------------------------------------------


async def test_buttons_that_would_spend_quota_are_refused(
    auth_client: AsyncClient, session: AsyncSession
) -> None:
    me = uuid.UUID((await auth_client.get("/auth/me")).json()["id"])
    assert (await auth_client.get("/settings/quota")).json()["exceeded"] == []
    await _use(session, me, lookups=LIMIT)

    some_id = uuid.uuid4()
    refused = [
        ("POST", "/outreach/build", None),
        ("POST", f"/outreach/{some_id}/regenerate", {}),
        ("POST", f"/outreach/{some_id}/retry", None),
        ("POST", f"/outreach/{some_id}/contact", {"email": "a@b.example"}),
        ("POST", "/matches/refresh", None),
        ("POST", f"/matches/{some_id}/tailor-preview", None),
        ("POST", f"/matches/{some_id}/find-contact", None),
        ("POST", f"/matches/{some_id}/draft", None),
        ("POST", "/prospects/refresh", None),
        ("POST", f"/prospects/matches/{some_id}/draft", None),
        ("POST", "/jobs/manual", {"url": "https://example.com/jobs/1"}),
        ("POST", "/resume/tag-skills", {"bullets": []}),
    ]
    for method, path, body in refused:
        response = await auth_client.request(method, path, json=body)
        assert response.status_code == 429, (path, response.text)
        assert response.json()["detail"]["code"] == "quota_exceeded", path
    upload = await auth_client.post(
        "/resume/upload", files={"file": ("cv.pdf", b"%PDF-1.4", "application/pdf")}
    )
    assert upload.status_code == 429

    quota = (await auth_client.get("/settings/quota")).json()
    assert quota["exceeded"] == ["contact_lookups"]
    assert quota["contact_lookups"] == LIMIT
    assert "contact lookups" in quota["message"]
    # Reading and reviewing still work.
    assert (await auth_client.get("/outreach")).status_code == 200


async def test_admin_sees_who_is_over_quota(auth_client: AsyncClient, session: AsyncSession) -> None:
    friend = User(email="friend@example.com", name="Friend")
    session.add(friend)
    await session.commit()
    await _use(session, friend.id, lookups=LIMIT)
    users = (await auth_client.get("/admin/usage")).json()["users"]
    row = next(u for u in users if u["email"] == "friend@example.com")
    assert row["quota_exceeded"] == ["contact_lookups"]
