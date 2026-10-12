"""Scheduling and sending approved emails (PLAN.md Phase 7, §8 `schedule_and_send`).

Approved items get a `scheduled_at` inside the user's send window (weekdays, their timezone) spaced
3-12 minutes apart and under the daily cap. At send time everything is checked again inside one
transaction holding row locks (the user's preferences row serialises the cap count; the outreach and
contact rows are locked too):

- invariant 1: an `approved` event by the owning user, newer than the last change to the text;
- invariant 3: the daily cap (sends counted by event time, in the user's timezone) and suppression;
- invariant 4: the global 30-day contact cooldown (follow-ups in the same thread are exempt);
- invariant 11: the attached PDF exists and passed the ATS check;
- the user isn't paused and their Gmail authorisation is healthy.

A check that fails because of the email itself sends it back to review (`send_failed` →
`pending_review`, reason in the event). Pauses, expired Gmail authorisation and a full day just
leave it scheduled for later.
"""

import asyncio
import logging
import random
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import DateTime, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Contact, Outreach, OutreachEvent, SuppressionEntry, User, UserPreferences
from app.models.enums import EmailSource, OutreachEventType, OutreachStatus
from app.services.contacts.selector import COOLDOWN_DAYS
from app.services.email.connection import GmailFactory, get_token_row, mark_needs_reauth
from app.services.email.gmail import Attachment, GmailError, GmailNotConnectedError, OutgoingEmail
from app.services.email.state import transition
from app.services.google.oauth import GoogleReauthRequiredError
from app.services.resume.files import find_pdf

log = logging.getLogger(__name__)

S = OutreachStatus
SEND_EVENTS = (OutreachEventType.SENT, OutreachEventType.FOLLOWUP_SENT)
# Events that change what would be sent: an approval only counts if it came after the last of these.
CONTENT_EVENTS = (
    OutreachEventType.DRAFTED,
    OutreachEventType.EDITED,
    OutreachEventType.REGENERATED,
    OutreachEventType.FOLLOWUP_DRAFTED,
    OutreachEventType.CONTACT_CHANGED,
)
STALE_AFTER = timedelta(minutes=30)  # a scheduled send this late (pause, outage) gets a new slot


def user_tz(user: User) -> ZoneInfo:
    try:
        return ZoneInfo(user.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("Asia/Kolkata")


@dataclass
class Window:
    start: time
    end: time
    tz: ZoneInfo

    def opens(self, day: date) -> datetime:
        return datetime.combine(day, self.start, self.tz)

    def closes(self, day: date) -> datetime:
        return datetime.combine(day, self.end, self.tz)

    def contains(self, moment: datetime) -> bool:
        local = moment.astimezone(self.tz)
        return local.weekday() < 5 and self.opens(local.date()) <= local < self.closes(local.date())


def _gap(rng: random.Random) -> timedelta:
    settings = get_settings()
    return timedelta(minutes=rng.uniform(settings.send_jitter_min_minutes, settings.send_jitter_max_minutes))


def next_slot(
    after: datetime, window: Window, rng: random.Random, day_counts: dict[date, int], cap: int
) -> datetime:
    """The first moment, a random 3-12 minutes after `after`, that is inside the send window on a
    weekday whose count is below the cap. Pure apart from `rng`, so it's tested directly."""
    candidate = after.astimezone(window.tz) + _gap(rng)
    for _ in range(366):
        day = candidate.date()
        if candidate.weekday() >= 5 or day_counts.get(day, 0) >= cap or candidate >= window.closes(day):
            nxt = day + timedelta(days=1)
            candidate = window.opens(nxt) + _gap(rng)
            continue
        if candidate < window.opens(day):
            candidate = window.opens(day) + _gap(rng)
            continue
        return candidate.astimezone(UTC)
    raise ValueError("no send slot within a year (is the daily cap 0?)")


@dataclass
class SendSummary:
    scheduled: int = 0
    sent: int = 0
    returned: int = 0  # sent back to review
    waiting: int = 0  # left scheduled: paused, Gmail needs reconnecting, cap reached, not in window
    reasons: dict[str, int] = field(default_factory=dict)

    def note(self, reason: str) -> None:
        self.reasons[reason] = self.reasons.get(reason, 0) + 1


async def _sends_on(session: AsyncSession, user_id: uuid.UUID, day: date, tz: ZoneInfo) -> int:
    """Emails (first sends and follow-ups) this user sent on `day` in their timezone, by the send
    time recorded on each `sent`/`followup_sent` event."""
    start = datetime.combine(day, time(0), tz)
    sent_at = cast(OutreachEvent.payload["sent_at"].astext, DateTime(timezone=True))
    return int(
        await session.scalar(
            select(func.count())
            .select_from(OutreachEvent)
            .where(
                OutreachEvent.user_id == user_id,
                OutreachEvent.type.in_(SEND_EVENTS),
                sent_at >= start,
                sent_at < start + timedelta(days=1),
            )
        )
        or 0
    )


async def approval_is_current(session: AsyncSession, outreach: Outreach) -> bool:
    """Invariant 1: an `approved` event by the owner exists and is newer than every change to what
    would be sent."""
    approved = await session.scalar(
        select(func.max(OutreachEvent.created_at)).where(
            OutreachEvent.outreach_id == outreach.id,
            OutreachEvent.user_id == outreach.user_id,
            OutreachEvent.type == OutreachEventType.APPROVED,
            OutreachEvent.payload["actor"].astext == str(outreach.user_id),
        )
    )
    if approved is None:
        return False
    changed = await session.scalar(
        select(func.max(OutreachEvent.created_at)).where(
            OutreachEvent.outreach_id == outreach.id, OutreachEvent.type.in_(CONTENT_EVENTS)
        )
    )
    return changed is None or approved > changed


class Scheduler:
    def __init__(self, gmail: GmailFactory, rng: random.Random | None = None) -> None:
        self._gmail = gmail
        self._rng = rng or random.Random()

    async def _prefs(self, session: AsyncSession, user_id: uuid.UUID, lock: bool = False) -> UserPreferences:
        query = select(UserPreferences).where(UserPreferences.user_id == user_id)
        prefs = await session.scalar(query.with_for_update() if lock else query)
        if prefs is None:
            prefs = UserPreferences(user_id=user_id)
            session.add(prefs)
            await session.flush()
            await session.refresh(prefs)
        return prefs

    async def schedule(self, session: AsyncSession, user: User, now: datetime) -> int:
        """Give approved items (and scheduled ones gone stale) a slot. Caller commits."""
        prefs = await self._prefs(session, user.id, lock=True)
        window = Window(prefs.send_window_start, prefs.send_window_end, user_tz(user))
        rows = (
            await session.scalars(
                select(Outreach)
                .where(Outreach.user_id == user.id, Outreach.status.in_([S.APPROVED, S.SCHEDULED]))
                .order_by(Outreach.updated_at, Outreach.id)
            )
        ).all()
        stale = [
            o
            for o in rows
            if o.status == S.SCHEDULED and o.scheduled_at and o.scheduled_at < now - STALE_AFTER
        ]
        todo = [o for o in rows if o.status == S.APPROVED] + stale
        if not todo:
            return 0
        keep = [o for o in rows if o.status == S.SCHEDULED and o not in stale and o.scheduled_at]
        counts: dict[date, int] = {}
        today = now.astimezone(window.tz).date()
        counts[today] = await _sends_on(session, user.id, today, window.tz)
        for o in keep:
            day = o.scheduled_at.astimezone(window.tz).date()  # type: ignore[union-attr]
            counts[day] = counts.get(day, 0) + 1
        last = max([o.scheduled_at for o in keep if o.scheduled_at] + [now - _gap(self._rng)])
        for outreach in todo:
            slot = next_slot(max(last, now), window, self._rng, counts, prefs.daily_send_cap)
            day = slot.astimezone(window.tz).date()
            counts[day] = counts.get(day, 0) + 1
            outreach.scheduled_at = slot
            last = slot
            if outreach.status == S.APPROVED:
                await transition(
                    session, outreach, S.SCHEDULED, actor_id=None, payload={"scheduled_at": slot.isoformat()}
                )
        return len(todo)

    async def _return_to_review(
        self, session: AsyncSession, outreach: Outreach, reason: str, message: str
    ) -> None:
        await transition(
            session,
            outreach,
            S.SEND_FAILED,
            actor_id=None,
            payload={"reason": reason, "message": message[:500]},
        )
        await transition(
            session,
            outreach,
            S.PENDING_REVIEW,
            actor_id=None,
            event=OutreachEventType.SEND_FAILED,
            payload={"returned_to_review": True, "reason": reason},
        )

    async def send_one(self, session: AsyncSession, user: User, outreach_id: uuid.UUID, now: datetime) -> str:
        """Send one due item if every check passes. Returns what happened. Caller commits."""
        prefs = await self._prefs(session, user.id, lock=True)  # serialises the cap count per user
        outreach = await session.scalar(
            select(Outreach).where(Outreach.id == outreach_id, Outreach.user_id == user.id).with_for_update()
        )
        if outreach is None or outreach.status != S.SCHEDULED:
            return "not_scheduled"
        if outreach.scheduled_at is None or outreach.scheduled_at > now:
            return "not_due"
        if not await approval_is_current(session, outreach):  # invariant 1
            await self._return_to_review(
                session, outreach, "not_approved", "No current approval for this text."
            )
            return "not_approved"
        if prefs.paused:
            return "paused"
        token = await get_token_row(session, user.id)
        if token is not None and token.needs_reauth:
            return "needs_reauth"
        window = Window(prefs.send_window_start, prefs.send_window_end, user_tz(user))
        if not window.contains(now):
            return "outside_window"  # the next schedule() run gives it a fresh slot
        today = now.astimezone(window.tz).date()
        if await _sends_on(session, user.id, today, window.tz) >= prefs.daily_send_cap:  # invariant 3
            return "cap_reached"

        contact = (
            await session.scalar(select(Contact).where(Contact.id == outreach.contact_id).with_for_update())
            if outreach.contact_id
            else None
        )
        if contact is None:
            await self._return_to_review(session, outreach, "no_contact", "The contact is missing.")
            return "no_contact"
        if contact.email_source == EmailSource.FAKE and not get_settings().use_fakes:
            await self._return_to_review(
                session, outreach, "fake_contact",
                "This contact was made up in USE_FAKES mode; choose a real one before sending.",
            )  # fmt: skip
            return "fake_contact"
        if await session.scalar(
            select(SuppressionEntry.id).where(func.lower(SuppressionEntry.email) == contact.email.lower())
        ):  # invariant 3
            await self._return_to_review(
                session, outreach, "suppressed", "This address asked not to be contacted."
            )
            return "suppressed"
        followup = outreach.followup_count > 0 and outreach.gmail_thread_id is not None
        if (
            not followup
            and contact.last_contacted_at is not None
            and now - contact.last_contacted_at < timedelta(days=COOLDOWN_DAYS)
        ):  # invariant 4
            await self._return_to_review(
                session,
                outreach,
                "contact_cooldown",
                f"Someone emailed this person in the last {COOLDOWN_DAYS} days.",
            )
            return "contact_cooldown"
        attachment = None
        if not followup:
            pdf = find_pdf(outreach.user_id, str(outreach.id))
            if pdf is None or not ((outreach.tailored_resume or {}).get("ats") or {}).get("passed"):
                await self._return_to_review(
                    session, outreach, "resume_missing", "The resume is missing or failed ATS."
                )
                return "resume_missing"  # invariant 11
            attachment = Attachment(filename=pdf.name, data=await asyncio.to_thread(pdf.read_bytes))

        try:
            gmail = await self._gmail(session, user)
            in_reply_to = None
            if followup:
                thread = await gmail.get_thread(outreach.gmail_thread_id)  # type: ignore[arg-type]
                in_reply_to = next((m.rfc_message_id for m in reversed(thread) if m.rfc_message_id), None)
            sent = await gmail.send(
                OutgoingEmail(
                    to=contact.email,
                    subject=outreach.subject or "",
                    body=outreach.body or "",
                    attachment=attachment,
                    thread_id=outreach.gmail_thread_id if followup else None,
                    in_reply_to=in_reply_to,
                )
            )
        except GoogleReauthRequiredError:
            await mark_needs_reauth(session, user.id)
            return "needs_reauth"
        except GmailNotConnectedError:
            return "not_connected"
        except GmailError as exc:
            await self._return_to_review(session, outreach, "gmail_error", str(exc))
            return "gmail_error"

        if not followup:
            outreach.gmail_message_id = sent.message_id
            outreach.gmail_thread_id = sent.thread_id
            outreach.sent_at = now
        contact.last_contacted_at = now
        await transition(
            session,
            outreach,
            S.SENT,
            actor_id=None,
            event=OutreachEventType.FOLLOWUP_SENT if followup else OutreachEventType.SENT,
            payload={
                "message_id": sent.message_id,
                "recipient": contact.email,
                "sent_at": now.isoformat(),
                "subject": outreach.subject,
                "body": outreach.body,
            },
        )
        return "sent"

    async def run_for_user(
        self, session: AsyncSession, user: User, now: datetime | None = None
    ) -> SendSummary:
        """schedule() then send what's due, committing after each send."""
        now = now or datetime.now(UTC)
        summary = SendSummary(scheduled=await self.schedule(session, user, now))
        await session.commit()
        due = (
            await session.scalars(
                select(Outreach.id)
                .where(
                    Outreach.user_id == user.id, Outreach.status == S.SCHEDULED, Outreach.scheduled_at <= now
                )
                .order_by(Outreach.scheduled_at)
            )
        ).all()
        for outreach_id in due:
            result = await self.send_one(session, user, outreach_id, now)
            await session.commit()
            summary.note(result)
            if result == "sent":
                summary.sent += 1
            elif result in ("paused", "needs_reauth", "not_connected", "cap_reached", "outside_window"):
                summary.waiting += 1
                break  # the same holds for the rest of this user's queue
            elif result not in ("not_scheduled", "not_due"):
                summary.returned += 1
        return summary
