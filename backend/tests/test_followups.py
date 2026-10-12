"""Phase 7: one short follow-up, drafted into the review queue when a sent email gets no reply."""

from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Outreach, OutreachEvent, User
from app.models.enums import OutreachEventType, OutreachStatus
from app.services.email.drafter import OPT_OUT_LINES
from app.services.email.followups import Followups, followup_subject
from app.services.llm.client import LLMQuotaExhaustedError
from app.services.llm.fake import FakeLLMClient
from tests.matching_fixtures import seed_matching_user
from tests.sending_fixtures import MONDAY_11_IST, sendable

S = OutreachStatus
NUDGE = {
    "body": "Following up on my note last week about the backend intern role. If a referral isn't "
    "possible, a pointer to whoever's hiring would help a lot."
}


async def _sent(session: AsyncSession, days_ago: int, **values: object) -> tuple[User, Outreach]:
    user = await seed_matching_user(session)  # resume (for the signature), preferences, Gemini key
    outreach = await sendable(session, user)
    await session.execute(
        update(Outreach)
        .where(Outreach.id == outreach.id)
        .values(
            status=S.SENT,
            sent_at=MONDAY_11_IST - timedelta(days=days_ago),
            gmail_thread_id="t-1",
            **values,
        )
    )
    await session.commit()
    await session.refresh(outreach)
    return user, outreach


async def test_a_follow_up_is_drafted_after_the_wait(session: AsyncSession) -> None:
    user, outreach = await _sent(session, days_ago=7)
    original = (outreach.subject, outreach.body)
    llm = FakeLLMClient(responses={"draft_followup": NUDGE})
    summary = await Followups(llm).run_for_user(session, user.id, MONDAY_11_IST)
    assert summary.drafted == 1
    await session.refresh(outreach)
    assert outreach.status == S.PENDING_REVIEW
    assert outreach.followup_count == 1
    assert outreach.subject == followup_subject(original[0])
    assert outreach.subject.startswith("Re: ")
    assert outreach.body is not None
    assert outreach.body.startswith("Hi Priya,\n\nFollowing up on my note")
    assert set(outreach.body.splitlines()) & set(OPT_OUT_LINES)
    event = await session.scalar(
        select(OutreachEvent).where(OutreachEvent.type == OutreachEventType.FOLLOWUP_DRAFTED)
    )
    assert event is not None
    assert event.payload["original"] == {"subject": original[0], "body": original[1]}
    [(request, prompt)] = llm.calls
    assert request.tier == "smart"
    assert '"days_since": 7' in prompt

    # Never a second one.
    assert (
        await Followups(llm).run_for_user(session, user.id, MONDAY_11_IST + timedelta(days=30))
    ).drafted == 0


async def test_no_follow_up_before_the_wait_or_after_a_reply(session: AsyncSession) -> None:
    user, _ = await _sent(session, days_ago=3)
    llm = FakeLLMClient(responses={"draft_followup": NUDGE})
    assert (await Followups(llm).run_for_user(session, user.id, MONDAY_11_IST)).drafted == 0
    await session.execute(
        update(Outreach).values(replied_at=MONDAY_11_IST, sent_at=MONDAY_11_IST - timedelta(days=9))
    )
    await session.commit()
    assert (await Followups(llm).run_for_user(session, user.id, MONDAY_11_IST)).drafted == 0
    assert llm.calls == []


async def test_an_overlong_follow_up_is_retried(session: AsyncSession) -> None:
    user, _ = await _sent(session, days_ago=8)
    long = {"body": " ".join(["word"] * 70) + "."}
    llm = FakeLLMClient(responses={"draft_followup": [long, NUDGE]})
    assert (await Followups(llm).run_for_user(session, user.id, MONDAY_11_IST)).drafted == 1
    assert "[too_long]" in llm.calls[1][1]


async def test_quota_exhaustion_leaves_it_due_for_the_next_run(session: AsyncSession) -> None:
    user, outreach = await _sent(session, days_ago=7)
    llm = FakeLLMClient()

    def exhausted(prompt: str) -> object:
        raise LLMQuotaExhaustedError("daily quota")

    llm.add_responder("draft_followup", exhausted)
    summary = await Followups(llm).run_for_user(session, user.id, MONDAY_11_IST)
    assert summary.stopped == "LLMQuotaExhaustedError"
    await session.refresh(outreach)
    assert outreach.status == S.FOLLOWUP_DUE
    assert outreach.followup_count == 0

    retry = FakeLLMClient(responses={"draft_followup": NUDGE})
    assert (await Followups(retry).run_for_user(session, user.id, MONDAY_11_IST)).drafted == 1
