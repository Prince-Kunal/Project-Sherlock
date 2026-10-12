"""Phase 7: slotting approved emails into the send window, and sending with every send-time check
(approval, cap, suppression, cooldown, pause, Gmail health, ATS PDF) on the FakeGmailClient."""

import itertools
import random
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Contact, Outreach, OutreachEvent, SuppressionEntry, UserPreferences
from app.models.enums import OutreachEventType, OutreachStatus, SuppressionReason
from app.services.email.connection import get_token_row, save_google_tokens
from app.services.email.gmail import GmailClient, GmailError, OutgoingEmail, SentMessage, ThreadMessage
from app.services.email.scheduler import Scheduler, Window, next_slot
from app.services.google.oauth import SCOPES, GoogleIdentity, GoogleReauthRequiredError, GoogleTokens
from tests.sending_fixtures import MONDAY_11_IST, PDF, fake_mailbox, mailbox_factory, sendable, sender

IST = ZoneInfo("Asia/Kolkata")
WINDOW = Window(time(9, 30), time(18, 0), IST)
S = OutreachStatus


def _local(moment: datetime) -> datetime:
    return moment.astimezone(IST)


# --- Slotting ------------------------------------------------------------------------------------------


def test_a_slot_inside_the_window_is_3_to_12_minutes_later() -> None:
    rng = random.Random(1)
    for _ in range(50):
        slot = next_slot(MONDAY_11_IST, WINDOW, rng, {}, cap=15)
        assert timedelta(minutes=3) <= slot - MONDAY_11_IST <= timedelta(minutes=12)


@pytest.mark.parametrize(
    ("after_local", "expected_day"),
    [
        (datetime(2026, 10, 12, 17, 55, tzinfo=IST), date(2026, 10, 13)),  # Monday after hours → Tuesday
        (datetime(2026, 10, 16, 17, 58, tzinfo=IST), date(2026, 10, 19)),  # Friday evening → Monday
        (datetime(2026, 10, 17, 11, 0, tzinfo=IST), date(2026, 10, 19)),  # Saturday → Monday
        (datetime(2026, 10, 13, 6, 0, tzinfo=IST), date(2026, 10, 13)),  # before the window → same day
    ],
)
def test_slots_skip_nights_and_weekends(after_local: datetime, expected_day: date) -> None:
    slot = _local(next_slot(after_local, WINDOW, random.Random(2), {}, cap=15))
    assert slot.date() == expected_day
    assert time(9, 33) <= slot.time() <= time(9, 42)


def test_a_full_day_moves_to_the_next_weekday() -> None:
    slot = _local(next_slot(MONDAY_11_IST, WINDOW, random.Random(3), {date(2026, 10, 12): 15}, cap=15))
    assert slot.date() == date(2026, 10, 13)


def test_a_zero_cap_never_finds_a_slot() -> None:
    with pytest.raises(ValueError, match="cap"):
        next_slot(MONDAY_11_IST, WINDOW, random.Random(4), {}, cap=0)


# --- Sending -------------------------------------------------------------------------------------------


async def _events(session: AsyncSession, outreach: Outreach) -> list[OutreachEventType]:
    rows = await session.scalars(
        select(OutreachEvent.type)
        .where(OutreachEvent.outreach_id == outreach.id)
        .order_by(OutreachEvent.created_at)
    )
    return list(rows.all())


async def test_approved_is_scheduled_then_sent_with_the_resume(session: AsyncSession) -> None:
    user = await sender(session)
    outreach = await sendable(session, user)
    mailbox = fake_mailbox(user)
    scheduler = Scheduler(mailbox_factory(mailbox), random.Random(5))

    first = await scheduler.run_for_user(session, user, MONDAY_11_IST)
    assert (first.scheduled, first.sent) == (1, 0)  # slotted 3-12 minutes out, not sent yet
    await session.refresh(outreach)
    assert outreach.status == S.SCHEDULED
    assert outreach.scheduled_at is not None
    assert timedelta(minutes=3) <= outreach.scheduled_at - MONDAY_11_IST <= timedelta(minutes=12)

    later = await scheduler.run_for_user(session, user, MONDAY_11_IST + timedelta(minutes=13))
    assert later.sent == 1
    await session.refresh(outreach)
    assert outreach.status == S.SENT
    assert outreach.gmail_thread_id is not None
    assert outreach.sent_at == MONDAY_11_IST + timedelta(minutes=13)
    [email] = mailbox.sent
    assert email.to == (await session.get(Contact, outreach.contact_id)).email  # type: ignore[union-attr]
    assert email.attachment is not None
    assert (email.attachment.filename, email.attachment.data) == ("Rohan_Das_Resume.pdf", PDF)
    assert email.thread_id is None
    contact = await session.get(Contact, outreach.contact_id)
    assert contact is not None
    assert contact.last_contacted_at == outreach.sent_at
    assert await _events(session, outreach) == [
        OutreachEventType.DRAFTED,
        OutreachEventType.APPROVED,
        OutreachEventType.SCHEDULED,
        OutreachEventType.SENT,
    ]


async def test_several_approvals_are_spaced_out(session: AsyncSession) -> None:
    user = await sender(session)
    rows = [await sendable(session, user) for _ in range(4)]
    await Scheduler(mailbox_factory(fake_mailbox(user)), random.Random(6)).schedule(
        session, user, MONDAY_11_IST
    )
    times = sorted([r.scheduled_at for r in rows if r.scheduled_at])
    assert len(times) == 4
    for a, b in itertools.pairwise(times):
        assert timedelta(minutes=3) <= b - a <= timedelta(minutes=12)


async def _force_due(session: AsyncSession, *rows: Outreach) -> None:
    for row in rows:
        await session.execute(
            update(Outreach)
            .where(Outreach.id == row.id)
            .values(scheduled_at=MONDAY_11_IST - timedelta(minutes=1))
        )
    await session.commit()


async def test_the_daily_cap_blocks_the_next_send(session: AsyncSession) -> None:
    user = await sender(session, daily_send_cap=2)
    rows = [await sendable(session, user) for _ in range(3)]
    mailbox = fake_mailbox(user)
    scheduler = Scheduler(mailbox_factory(mailbox), random.Random(7))
    await scheduler.schedule(session, user, MONDAY_11_IST - timedelta(minutes=20))
    await session.commit()
    # The scheduler already put the third on Tuesday; force all three due now to test the send-time check.
    await _force_due(session, *rows)
    summary = await scheduler.run_for_user(session, user, MONDAY_11_IST)
    assert summary.sent == 2
    assert summary.reasons.get("cap_reached") == 1
    assert len(mailbox.sent) == 2
    statuses = sorted([(await session.get(Outreach, r.id)).status for r in rows])  # type: ignore[union-attr]
    assert statuses == [S.SCHEDULED, S.SENT, S.SENT]


async def test_a_suppressed_address_never_gets_an_email(session: AsyncSession) -> None:
    user = await sender(session)
    outreach = await sendable(session, user, email="optout@acme.example")
    session.add(SuppressionEntry(email="OptOut@acme.example", reason=SuppressionReason.OPT_OUT))
    await session.commit()
    mailbox = fake_mailbox(user)
    scheduler = Scheduler(mailbox_factory(mailbox), random.Random(8))
    await scheduler.schedule(session, user, MONDAY_11_IST)
    await session.commit()
    await _force_due(session, outreach)
    summary = await scheduler.run_for_user(session, user, MONDAY_11_IST)
    assert summary.reasons == {"suppressed": 1}
    assert mailbox.sent == []
    await session.refresh(outreach)
    assert outreach.status == S.PENDING_REVIEW  # back for review, with the reason
    from app.services.contacts.views import outreach_list_item

    assert "asked not to be contacted" in ((await outreach_list_item(session, outreach)).send_error or "")


async def test_the_global_cooldown_holds_at_send_time(session: AsyncSession) -> None:
    user = await sender(session)
    outreach = await sendable(session, user)
    await session.execute(
        update(Contact)
        .where(Contact.id == outreach.contact_id)
        .values(last_contacted_at=MONDAY_11_IST - timedelta(days=5))
    )
    await session.commit()
    mailbox = fake_mailbox(user)
    scheduler = Scheduler(mailbox_factory(mailbox), random.Random(9))
    await scheduler.schedule(session, user, MONDAY_11_IST)
    await session.commit()
    await _force_due(session, outreach)
    assert (await scheduler.run_for_user(session, user, MONDAY_11_IST)).reasons == {"contact_cooldown": 1}
    assert mailbox.sent == []


@pytest.mark.parametrize("blocker", ["paused", "needs_reauth", "weekend"])
async def test_paused_expired_gmail_and_weekends_wait_without_sending(
    session: AsyncSession, blocker: str
) -> None:
    user = await sender(session, paused=blocker == "paused")
    outreach = await sendable(session, user)
    if blocker == "needs_reauth":
        await save_google_tokens(session, user.id, _tokens(user.email))
        (await get_token_row(session, user.id)).needs_reauth = True  # type: ignore[union-attr]
        await session.commit()
    mailbox = fake_mailbox(user)
    scheduler = Scheduler(mailbox_factory(mailbox), random.Random(10))
    await scheduler.schedule(session, user, MONDAY_11_IST)
    await session.commit()
    await _force_due(session, outreach)
    now = MONDAY_11_IST + timedelta(days=5) if blocker == "weekend" else MONDAY_11_IST  # Saturday
    summary = await scheduler.run_for_user(session, user, now)
    assert mailbox.sent == []
    assert summary.waiting == 1 or blocker == "weekend"
    await session.refresh(outreach)
    assert outreach.status == S.SCHEDULED  # nothing wrong with the email: it waits


def _tokens(email: str) -> GoogleTokens:
    return GoogleTokens(
        identity=GoogleIdentity(email=email, email_verified=True, name="R", subject="s"),
        refresh_token="refresh-1",
        scopes=list(SCOPES),
        access_token="a",
        expires_in=3600,
    )


class _Failing(GmailClient):
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def send(self, message: OutgoingEmail) -> SentMessage:
        raise self.error

    async def get_thread(self, thread_id: str) -> list[ThreadMessage]:
        raise self.error


async def test_a_gmail_error_sends_it_back_to_review(session: AsyncSession) -> None:
    user = await sender(session)
    outreach = await sendable(session, user)
    scheduler = Scheduler(
        mailbox_factory(_Failing(GmailError("gmail messages/send: 400 invalid To"))), random.Random(11)
    )
    await scheduler.schedule(session, user, MONDAY_11_IST)
    await session.commit()
    await _force_due(session, outreach)
    assert (await scheduler.run_for_user(session, user, MONDAY_11_IST)).returned == 1
    await session.refresh(outreach)
    assert outreach.status == S.PENDING_REVIEW


async def test_an_expired_google_token_pauses_sending(session: AsyncSession) -> None:
    user = await sender(session)
    await save_google_tokens(session, user.id, _tokens(user.email))
    outreach = await sendable(session, user)
    await session.commit()
    failing = _Failing(GoogleReauthRequiredError("Token has been expired or revoked."))
    scheduler = Scheduler(mailbox_factory(failing), random.Random(12))
    await scheduler.schedule(session, user, MONDAY_11_IST)
    await session.commit()
    await _force_due(session, outreach)
    assert (await scheduler.run_for_user(session, user, MONDAY_11_IST)).reasons == {"needs_reauth": 1}
    row = await get_token_row(session, user.id)
    assert row is not None
    assert row.needs_reauth is True
    await session.refresh(outreach)
    assert outreach.status == S.SCHEDULED


async def test_a_follow_up_goes_in_the_same_thread_without_the_resume(session: AsyncSession) -> None:
    user = await sender(session)
    outreach = await sendable(session, user)
    mailbox = fake_mailbox(user)
    scheduler = Scheduler(mailbox_factory(mailbox), random.Random(13))
    await scheduler.schedule(session, user, MONDAY_11_IST)
    await session.commit()
    await _force_due(session, outreach)
    await scheduler.run_for_user(session, user, MONDAY_11_IST)
    await session.refresh(outreach)
    thread_id = outreach.gmail_thread_id
    first_rfc = (await mailbox.get_thread(thread_id))[0].rfc_message_id  # type: ignore[arg-type]

    # A week later the follow-up is drafted, reviewed and approved.
    from app.services.email.state import transition

    await transition(session, outreach, S.FOLLOWUP_DUE, actor_id=None)
    outreach.followup_count = 1
    outreach.subject, outreach.body = f"Re: {outreach.subject}", outreach.body
    await transition(
        session, outreach, S.PENDING_REVIEW, actor_id=None, event=OutreachEventType.FOLLOWUP_DRAFTED
    )
    await transition(session, outreach, S.APPROVED, actor_id=user.id)
    await session.commit()
    week_later = MONDAY_11_IST + timedelta(days=7)
    await scheduler.schedule(session, user, week_later)
    await session.commit()
    await session.execute(update(Outreach).where(Outreach.id == outreach.id).values(scheduled_at=week_later))
    await session.commit()
    assert (await scheduler.run_for_user(session, user, week_later)).sent == 1

    followup = mailbox.sent[-1]
    assert followup.thread_id == thread_id
    assert followup.in_reply_to == first_rfc
    assert followup.attachment is None
    await session.refresh(outreach)
    assert outreach.sent_at == MONDAY_11_IST  # the first send's time is kept
    assert (await _events(session, outreach))[-1] == OutreachEventType.FOLLOWUP_SENT
    # The global cooldown doesn't block a follow-up to the same person in the same thread.


async def test_stale_scheduled_items_get_a_fresh_slot(session: AsyncSession) -> None:
    user = await sender(session, paused=True)
    outreach = await sendable(session, user)
    scheduler = Scheduler(mailbox_factory(fake_mailbox(user)), random.Random(14))
    await scheduler.schedule(session, user, MONDAY_11_IST)
    await session.commit()
    await session.execute(
        update(UserPreferences).where(UserPreferences.user_id == user.id).values(paused=False)
    )
    await session.commit()
    two_hours = MONDAY_11_IST + timedelta(hours=2)
    await scheduler.schedule(session, user, two_hours)
    await session.commit()
    await session.refresh(outreach)
    assert outreach.scheduled_at is not None
    assert outreach.scheduled_at > two_hours  # not sent in a burst the moment sending resumes
    assert outreach.scheduled_at.tzinfo is not None
    assert outreach.scheduled_at.astimezone(UTC) - two_hours <= timedelta(minutes=12)


async def test_made_up_contacts_are_never_emailed_for_real(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A draft made with USE_FAKES=true has an invented contact, possibly at a real company's domain."""
    from app.core.config import get_settings
    from app.models.enums import EmailSource

    user = await sender(session)
    outreach = await sendable(session, user, email="vikram@hackerrank.com")
    await session.execute(
        update(Contact).where(Contact.id == outreach.contact_id).values(email_source=EmailSource.FAKE)
    )
    await session.commit()
    monkeypatch.setattr(get_settings(), "use_fakes", False)
    mailbox = fake_mailbox(user)
    scheduler = Scheduler(mailbox_factory(mailbox), random.Random(15))
    await scheduler.schedule(session, user, MONDAY_11_IST)
    await session.commit()
    await _force_due(session, outreach)
    assert (await scheduler.run_for_user(session, user, MONDAY_11_IST)).reasons == {"fake_contact": 1}
    assert mailbox.sent == []
    await session.refresh(outreach)
    assert outreach.status == S.PENDING_REVIEW
