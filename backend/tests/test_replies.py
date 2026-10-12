"""Phase 7: reply, bounce and opt-out detection on Gmail thread fixtures (users.threads.get, format
full), and what each does to the outreach, the contact and the suppression list."""

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Contact, Outreach, OutreachEvent, SuppressionEntry, User
from app.models.enums import OutreachEventType, OutreachStatus, SuppressionReason, VerificationStatus
from app.services.email.gmail import GmailClient, OutgoingEmail, SentMessage, ThreadMessage, parse_thread
from app.services.email.replies import ReplyChecker, classify, strip_quoted
from app.services.llm.fake import FakeLLMClient
from tests.conftest import FIXTURES
from tests.sending_fixtures import mailbox_factory, sendable, sender

ME = "rohan.das.dev@gmail.com"
SENT_AT = datetime(2026, 10, 7, 8, 0, tzinfo=UTC)
S = OutreachStatus


def thread(name: str) -> list[ThreadMessage]:
    return parse_thread(json.loads((FIXTURES / "sources" / "gmail" / f"{name}.json").read_text()))


class Threads(GmailClient):
    """Returns the named fixture for any thread id."""

    def __init__(self, name: str) -> None:
        self.messages = thread(name)

    async def send(self, message: OutgoingEmail) -> SentMessage:
        raise AssertionError("check_replies never sends")

    async def get_thread(self, thread_id: str) -> list[ThreadMessage]:
        return self.messages


# --- Parsing and classification ----------------------------------------------------------------------


def test_threads_parse_into_messages_oldest_first() -> None:
    sent, reply = thread("thread_reply")
    assert sent.from_address == ME
    assert sent.rfc_message_id == "<172839.1@gmail.com>"
    assert "Resume's attached" in sent.body  # the PDF part isn't mistaken for the body
    assert sent.snippet.startswith("Hi Priya, I'm applying")  # HTML entities decoded
    assert reply.from_address == "priya@ledgerline.example"
    assert reply.sent_at > sent.sent_at
    assert strip_quoted(reply.body) == "Hi Rohan, happy to refer you. Can you send me the job link?"


def test_html_only_replies_are_read_too() -> None:
    _, reply = thread("thread_html_reply")
    assert reply.body == "Sure, I'll pass it on to our hiring manager."


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("thread_reply", "reply"),
        ("thread_bounce", "bounce"),
        ("thread_opt_out", "opt_out"),
        ("thread_ambiguous", "maybe_opt_out"),
        ("thread_html_reply", "reply"),
    ],
)
def test_classification(name: str, kind: str) -> None:
    assert classify(thread(name)[-1]) == kind


def test_our_own_quoted_text_cannot_trigger_an_opt_out() -> None:
    _, reply = thread("thread_reply")
    quoted = reply.model_copy(update={"body": reply.body + "\n> please remove me"})  # inside the quote
    assert classify(quoted) == "reply"


def test_out_of_office_is_an_automatic_reply() -> None:
    _, auto = thread("thread_auto_reply")
    assert auto.auto_submitted is True


# --- What each one does -------------------------------------------------------------------------------


async def _sent(session: AsyncSession, status: S = S.SENT) -> tuple[User, Outreach]:
    user = await sender(session, email=ME)
    outreach = await sendable(session, user, email="priya@ledgerline.example")
    await session.execute(
        update(Outreach)
        .where(Outreach.id == outreach.id)
        .values(status=status, sent_at=SENT_AT, gmail_thread_id="18f2a0c0d1e2f300", gmail_message_id="m1")
    )
    await session.commit()
    await session.refresh(outreach)
    return user, outreach


async def _check(
    session: AsyncSession, user: User, name: str, llm: FakeLLMClient | None = None
) -> dict[str, Any]:
    summary = await ReplyChecker(mailbox_factory(Threads(name)), llm).run_for_user(session, user)
    return {"replied": summary.replied, "opted_out": summary.opted_out, "bounced": summary.bounced}


async def test_a_reply_marks_the_outreach_replied(session: AsyncSession) -> None:
    user, outreach = await _sent(session)
    assert await _check(session, user, "thread_reply") == {"replied": 1, "opted_out": 0, "bounced": 0}
    await session.refresh(outreach)
    assert outreach.status == S.REPLIED
    assert outreach.replied_at == datetime(2026, 10, 8, 8, 0, tzinfo=UTC)
    event = await session.scalar(
        select(OutreachEvent).where(OutreachEvent.type == OutreachEventType.REPLY_DETECTED)
    )
    assert event is not None
    assert event.payload["text"] == "Hi Rohan, happy to refer you. Can you send me the job link?"
    assert event.payload["sender"] == "priya@ledgerline.example"
    # Checking again changes nothing (replied threads aren't watched any more).
    assert await _check(session, user, "thread_reply") == {"replied": 0, "opted_out": 0, "bounced": 0}


@pytest.mark.parametrize("stage", [S.FOLLOWUP_DUE, S.PENDING_REVIEW, S.SCHEDULED])
async def test_a_reply_cancels_a_pending_follow_up(session: AsyncSession, stage: S) -> None:
    user, outreach = await _sent(session, status=stage)
    await _check(session, user, "thread_reply")
    await session.refresh(outreach)
    assert outreach.status == S.REPLIED


async def test_a_bounce_invalidates_and_suppresses_the_address(session: AsyncSession) -> None:
    user, outreach = await _sent(session)
    assert (await _check(session, user, "thread_bounce"))["bounced"] == 1
    await session.refresh(outreach)
    assert outreach.status == S.FAILED
    assert outreach.failure_reason == "bounced"
    contact = await session.get(Contact, outreach.contact_id)
    assert contact is not None
    assert contact.verification_status == VerificationStatus.INVALID
    entry = await session.scalar(
        select(SuppressionEntry).where(SuppressionEntry.email == "priya@ledgerline.example")
    )
    assert entry is not None
    assert entry.reason == SuppressionReason.BOUNCE


async def test_an_opt_out_suppresses_and_closes(session: AsyncSession) -> None:
    user, outreach = await _sent(session)
    assert (await _check(session, user, "thread_opt_out"))["opted_out"] == 1
    await session.refresh(outreach)
    assert outreach.status == S.CLOSED
    assert outreach.replied_at is not None
    entry = await session.scalar(
        select(SuppressionEntry).where(SuppressionEntry.email == "priya@ledgerline.example")
    )
    assert entry is not None
    assert entry.reason == SuppressionReason.OPT_OUT


async def test_automatic_replies_are_ignored(session: AsyncSession) -> None:
    user, outreach = await _sent(session)
    assert await _check(session, user, "thread_auto_reply") == {"replied": 0, "opted_out": 0, "bounced": 0}
    await session.refresh(outreach)
    assert outreach.status == S.SENT


async def test_ambiguous_wording_goes_to_the_llm_tiebreaker(session: AsyncSession) -> None:
    from tests.matching_fixtures import seed_matching_user

    user, outreach = await _sent(session)
    await seed_matching_user(session, user=user)  # gives the user a (fake) Gemini key
    llm = FakeLLMClient(responses={"classify_reply": {"intent": "reply"}})
    assert (await _check(session, user, "thread_ambiguous", llm))["replied"] == 1
    [(request, prompt)] = llm.calls
    assert request.tier == "fast"
    assert "not hiring interns this cycle" in prompt
    assert "won't follow up" not in prompt  # only the new text, not our quoted email
    await session.refresh(outreach)
    assert outreach.status == S.REPLIED


async def test_without_a_tiebreaker_ambiguous_wording_counts_as_an_opt_out(session: AsyncSession) -> None:
    user, outreach = await _sent(session)
    assert (await _check(session, user, "thread_ambiguous", llm=None))["opted_out"] == 1
    await session.refresh(outreach)
    assert outreach.status == S.CLOSED
