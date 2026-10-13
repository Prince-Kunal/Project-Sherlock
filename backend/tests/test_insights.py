"""Phase 10: A/B draft styles, the company research snippet, outcome analytics and the weekly summary."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis
from app.models import Company, Contact, Outreach, User, UserPreferences
from app.models.enums import Outcome, OutreachStatus, RoleCategory, SizeHint
from app.services.analytics import MIN_PER_VARIANT, outreach_analytics
from app.services.contacts.fake import FakeContactProvider
from app.services.email.drafter import Drafter, DraftInputs, research_sentences
from app.services.email.fake_gmail import FakeGmailClient
from app.services.email.pipeline import DraftPipeline
from app.services.email.summary import build_summary, send_summary, users_due_for_summary
from app.services.email.variants import STYLES, choose_variant
from app.services.registry import build_fake_llm_client
from app.services.resume.skills import get_lexicon
from tests.sending_fixtures import mailbox_factory, sendable, sender
from tests.test_prospects import _drafting_user, _job_matches

NOW = datetime(2026, 10, 12, 5, 30, tzinfo=UTC)  # Monday 11:00 IST


# --- A/B draft styles ---------------------------------------------------------------------------------


async def _with_variants(session: AsyncSession, user: User, variants: list[str | None]) -> None:
    for variant in variants:
        company = Company(name=f"V {uuid.uuid4().hex[:6]}")
        session.add(company)
        await session.flush()
        session.add(
            Outreach(
                user_id=user.id,
                company_id=company.id,
                campaign_type="open",
                status=OutreachStatus.CLOSED,
                draft_variant=variant,
            )
        )
    await session.commit()


async def test_styles_alternate_and_can_be_locked(session: AsyncSession) -> None:
    user = await sender(session)
    assert await choose_variant(session, user.id) == "a"
    await _with_variants(session, user, ["a", None])
    assert await choose_variant(session, user.id) == "b"
    await _with_variants(session, user, ["b"])
    assert await choose_variant(session, user.id) == "a"
    assert await choose_variant(session, user.id, "b") == "b"
    assert await choose_variant(session, user.id, "a") == "a"


async def test_the_daily_batch_writes_both_styles_and_regenerating_keeps_one(session: AsyncSession) -> None:
    user = await _drafting_user(session, batch=4, share=0)
    await _job_matches(session, user, 4)
    llm = build_fake_llm_client()
    contacts = FakeContactProvider()
    pipeline = DraftPipeline(llm, lambda _key: contacts)
    summary = await pipeline.build_for_user(session, user.id)
    assert summary.drafted == 4
    rows = (
        await session.scalars(
            select(Outreach).where(Outreach.user_id == user.id).order_by(Outreach.created_at)
        )
    ).all()
    assert [o.draft_variant for o in rows] == ["a", "b", "a", "b"]
    prompts = [prompt for request, prompt in llm.calls if request.prompt_name == "draft_email"]
    assert STYLES["a"] in prompts[0]
    assert STYLES["b"] in prompts[1]

    llm.calls.clear()
    await pipeline.regenerate(session, rows[1], hint=None, api_key=None)
    [prompt] = [p for r, p in llm.calls if r.prompt_name == "draft_email"]
    assert STYLES["b"] in prompt
    await session.refresh(rows[1])
    assert rows[1].draft_variant == "b"


async def test_a_locked_style_is_used_for_every_draft(session: AsyncSession) -> None:
    user = await _drafting_user(session, batch=2, share=0)
    await session.execute(
        update(UserPreferences).where(UserPreferences.user_id == user.id).values(draft_style="b")
    )
    await session.commit()
    await _job_matches(session, user, 2)
    await DraftPipeline(build_fake_llm_client(), lambda _key: FakeContactProvider()).build_for_user(
        session, user.id
    )
    variants = (
        await session.scalars(select(Outreach.draft_variant).where(Outreach.user_id == user.id))
    ).all()
    assert variants == ["b", "b"]


# --- Company research snippet -------------------------------------------------------------------------

WEBSITE = (
    "Homepage:\nLedgerline makes accounting software for small businesses across India.\n\n"
    "About:\nWe are a team of forty people in Bengaluru who care about clean books.\n\n"
    "Latest blog post:\nThis quarter we moved our reconciliation service from Celery to a Go worker pool.\n"
    "We also rewrote the ledger API in Django with PostgreSQL row-level locking for concurrent posts.\n"
    "Thanks for reading."
)


def test_research_prefers_the_blog_sentence_naming_the_candidates_skills() -> None:
    company = Company(name="Ledgerline", website_text=WEBSITE)
    picked = research_sentences(company, {"django", "postgresql"}, get_lexicon(), limit=2)
    assert (
        picked[0]
        == "We also rewrote the ledger API in Django with PostgreSQL row-level locking for concurrent posts."
    )
    assert picked[1].startswith("This quarter we moved")  # the blog comes before About and Homepage
    assert research_sentences(Company(name="X"), {"django"}, get_lexicon()) == []


def test_research_sentences_become_hook_candidates() -> None:
    from app.models import Job

    company = Company(
        name="Ledgerline", website_text=WEBSITE, description="Ledgerline builds accounting software."
    )
    job = Job(
        title="Backend Intern", description_text="Build REST APIs in Python (Django) backed by PostgreSQL."
    )
    contact = Contact(full_name="Priya Nair", email="p@x.example", role_category=RoleCategory.ENG_MANAGER)
    inputs = DraftInputs(
        job=job, company=company, contact=contact, basics=None,  # type: ignore[arg-type]
        about_me="", highlights=[], skills={"django", "postgresql"},
        research=research_sentences(company, {"django", "postgresql"}, get_lexicon()),
    )  # fmt: skip
    contexts = Drafter(build_fake_llm_client()).contexts(inputs)
    assert contexts[0] == "Build REST APIs in Python (Django) backed by PostgreSQL."
    assert any("row-level locking" in c for c in contexts)


async def test_job_drafts_read_the_company_site_once(session: AsyncSession) -> None:
    user = await _drafting_user(session, batch=1, share=0)
    await _job_matches(session, user, 1)
    fetched: list[str] = []

    class Site:
        async def fetch(self, domain: str) -> str:
            fetched.append(domain)
            return WEBSITE

    pipeline = DraftPipeline(build_fake_llm_client(), lambda _key: FakeContactProvider(), fetcher=Site())  # type: ignore[arg-type]
    await pipeline.build_for_user(session, user.id)
    outreach = await session.scalar(select(Outreach).where(Outreach.user_id == user.id))
    assert outreach is not None
    assert outreach.status == OutreachStatus.PENDING_REVIEW
    company = await session.get(Company, outreach.company_id)
    assert company is not None
    assert company.website_text == WEBSITE
    assert fetched == ["hiring0.example"]


# --- Analytics ----------------------------------------------------------------------------------------


async def _sent(
    session: AsyncSession,
    user: User,
    *,
    role: RoleCategory,
    size: SizeHint,
    variant: str | None,
    replied: bool,
    outcome: Outcome = Outcome.NONE,
    days_ago: int = 3,
) -> None:
    outreach = await sendable(session, user)
    contact = await session.get(Contact, outreach.contact_id)
    company = await session.get(Company, outreach.company_id)
    assert contact is not None
    assert company is not None
    contact.role_category = role
    company.size_hint = size
    sent_at = NOW - timedelta(days=days_ago)
    outreach.status = OutreachStatus.REPLIED if replied else OutreachStatus.SENT
    outreach.sent_at = sent_at
    outreach.replied_at = sent_at + timedelta(hours=5) if replied else None
    outreach.draft_variant = variant
    outreach.outcome = outcome
    await session.commit()


async def test_reply_rates_by_role_stage_and_style(session: AsyncSession) -> None:
    user = await sender(session)
    await _sent(session, user, role=RoleCategory.FOUNDER, size=SizeHint.STARTUP, variant="a", replied=True,
                outcome=Outcome.REFERRED)  # fmt: skip
    await _sent(session, user, role=RoleCategory.FOUNDER, size=SizeHint.STARTUP, variant="b", replied=False)
    await _sent(session, user, role=RoleCategory.RECRUITER, size=SizeHint.LARGE, variant="b", replied=True)
    await _sent(session, user, role=RoleCategory.RECRUITER, size=SizeHint.LARGE, variant=None, replied=False,
                days_ago=200)  # fmt: skip
    result = await outreach_analytics(session, user.id, NOW, days=90)
    assert (result.sent, result.replied, result.referred, result.reply_rate) == (3, 2, 1, 66.7)
    roles = {b.key: (b.sent, b.replied) for b in result.by_role}
    assert roles == {"founder": (2, 1), "recruiter": (1, 1)}
    assert {b.key: b.reply_rate for b in result.by_stage} == {"startup": 50.0, "large": 100.0}
    assert {b.key: b.label for b in result.by_variant} == {"a": "Ask first", "b": "Work first"}
    assert result.leader is None
    assert "Too early" in result.verdict
    everything = await outreach_analytics(session, user.id, NOW, days=None)
    assert everything.sent == 4
    assert {b.key for b in everything.by_variant} == {"a", "b", "none"}


async def test_the_style_with_more_replies_is_named_once_there_is_enough_data(session: AsyncSession) -> None:
    user = await sender(session)
    for i in range(MIN_PER_VARIANT):
        await _sent(
            session, user, role=RoleCategory.ENG_MANAGER, size=SizeHint.MID, variant="a", replied=i < 1
        )
        await _sent(
            session, user, role=RoleCategory.ENG_MANAGER, size=SizeHint.MID, variant="b", replied=i < 4
        )
    result = await outreach_analytics(session, user.id, NOW)
    assert result.leader == "b"
    assert result.verdict.startswith("Work first gets more replies: 50.0% (4 of 8)")


async def test_analytics_api(auth_client: AsyncClient, session: AsyncSession) -> None:
    body = (await auth_client.get("/outreach/analytics")).json()
    assert (body["sent"], body["reply_rate"], body["draft_style"], body["by_role"]) == (0, None, "ab", [])
    assert (await auth_client.get("/outreach/analytics", params={"days": 3})).status_code == 422


# --- Weekly summary -----------------------------------------------------------------------------------


async def test_the_summary_says_what_happened_and_what_is_waiting(session: AsyncSession) -> None:
    user = await sender(session)
    await _sent(session, user, role=RoleCategory.FOUNDER, size=SizeHint.STARTUP, variant="a", replied=True)
    from app.models import OutreachEvent
    from app.models.enums import OutreachEventType

    outreach = await session.scalar(select(Outreach).where(Outreach.user_id == user.id))
    assert outreach is not None
    for kind in (OutreachEventType.SENT, OutreachEventType.REPLY_DETECTED):
        session.add(OutreachEvent(outreach_id=outreach.id, user_id=user.id, type=kind, payload={}))
    await sendable(session, user, approve=False)  # one draft in review
    await session.commit()

    summary = await build_summary(session, user, datetime.now(UTC))
    assert summary.subject == "Sherlock: 1 email sent, 1 reply"
    assert "Sent: 1 email." in summary.body
    assert "Replies: 1." in summary.body
    assert "1 draft waiting for your review." in summary.body
    assert "Too early to compare" in summary.body
    assert "/review" in summary.body
    assert not summary.empty


async def test_summaries_go_out_on_monday_morning_once_and_only_when_wanted(session: AsyncSession) -> None:
    user = await sender(session)  # Asia/Kolkata
    monday_0830_ist = datetime(2026, 10, 12, 3, 0, tzinfo=UTC)
    assert await users_due_for_summary(session, get_redis(), monday_0830_ist) == [user.id]
    assert await users_due_for_summary(session, get_redis(), monday_0830_ist + timedelta(minutes=20)) == []
    assert await users_due_for_summary(session, get_redis(), monday_0830_ist + timedelta(days=1)) == []

    mailbox = FakeGmailClient(user.email)
    assert await send_summary(session, user, mailbox_factory(mailbox), NOW) == "empty"
    await sendable(session, user, approve=False)
    assert await send_summary(session, user, mailbox_factory(mailbox), NOW) == "sent"
    [email] = mailbox.sent
    assert email.to == user.email
    assert email.attachment is None
    await session.execute(
        update(UserPreferences).where(UserPreferences.user_id == user.id).values(weekly_summary=False)
    )
    await session.commit()
    assert await send_summary(session, user, mailbox_factory(mailbox), NOW) == "off"
    assert len(mailbox.sent) == 1


@pytest.mark.parametrize("hour_utc", [2, 4])
async def test_no_summary_outside_the_hour(session: AsyncSession, hour_utc: int) -> None:
    await sender(session)
    assert (
        await users_due_for_summary(session, get_redis(), datetime(2026, 10, 12, hour_utc, 0, tzinfo=UTC))
        == []
    )
