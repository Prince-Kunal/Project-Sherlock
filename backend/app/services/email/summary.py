"""The weekly summary (PLAN.md Phase 10): every Monday at 08:30 the user's time, a short plain-text
email from the user's own Gmail to themselves: last week's sends, replies and outcomes, what's
waiting for them, and how the two email styles compare.

It goes only to the user's own address, so it isn't outreach: no approval record or opt-out line
applies (invariants 1 and 9 cover emails to contacts). Users switch it off in Settings
(`weekly_summary`). Nothing is sent for a week with nothing to report.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Outreach, OutreachEvent, User
from app.models.enums import Outcome, OutreachEventType, OutreachStatus
from app.services.analytics import outreach_analytics
from app.services.email.connection import GmailFactory, get_token_row
from app.services.email.gmail import GmailError, GmailNotConnectedError, OutgoingEmail
from app.services.google.oauth import GoogleAuthError
from app.services.matching.pipeline import load_preferences
from app.services.quotas import quota_status

log = logging.getLogger(__name__)

SUMMARY_WEEKDAY = 0  # Monday
SUMMARY_HOUR = 8  # the hourly cron runs at minute 30, so 08:30 local


@dataclass
class WeeklySummary:
    subject: str
    body: str
    empty: bool  # nothing happened and nothing is waiting: not worth an email


def _plural(n: int, word: str, many: str | None = None) -> str:
    return f"{n} {word if n == 1 else (many or word + 's')}"


async def build_summary(session: AsyncSession, user: User, now: datetime) -> WeeklySummary:
    week_ago = now - timedelta(days=7)
    events = dict(
        (
            await session.execute(
                select(OutreachEvent.type, func.count())
                .where(OutreachEvent.user_id == user.id, OutreachEvent.created_at >= week_ago)
                .group_by(OutreachEvent.type)
            )
        ).all()
    )
    sent = int(events.get(OutreachEventType.SENT, 0))
    followups = int(events.get(OutreachEventType.FOLLOWUP_SENT, 0))
    replies = int(events.get(OutreachEventType.REPLY_DETECTED, 0))
    outcomes = dict(
        (
            await session.execute(
                select(Outreach.outcome, func.count())
                .where(
                    Outreach.user_id == user.id,
                    Outreach.updated_at >= week_ago,
                    Outreach.outcome != Outcome.NONE,
                )
                .group_by(Outreach.outcome)
            )
        ).all()
    )
    waiting = dict(
        (
            await session.execute(
                select(Outreach.status, func.count())
                .where(
                    Outreach.user_id == user.id,
                    Outreach.status.in_([OutreachStatus.PENDING_REVIEW, OutreachStatus.FAILED]),
                )
                .group_by(Outreach.status)
            )
        ).all()
    )
    pending = int(waiting.get(OutreachStatus.PENDING_REVIEW, 0))
    failed = int(waiting.get(OutreachStatus.FAILED, 0))
    referred = int(outcomes.get(Outcome.REFERRED, 0))
    interviews = int(outcomes.get(Outcome.INTERVIEW, 0))

    lines = [f"Here's your week in Sherlock ({week_ago:%-d %b} to {now:%-d %b})."]
    lines.append("")
    lines.append(
        f"Sent: {_plural(sent, 'email')}"
        + (f" and {_plural(followups, 'follow-up')}" if followups else "")
        + "."
    )
    lines.append(f"Replies: {replies}.")
    if referred or interviews:
        lines.append(f"Outcomes you recorded: {referred} referred, {_plural(interviews, 'interview')}.")
    lines.append("")
    if pending:
        lines.append(f"{_plural(pending, 'draft')} waiting for your review.")
    if failed:
        lines.append(f"{_plural(failed, 'draft')} need attention (no contact found, or a check failed).")
    if not pending and not failed:
        lines.append("Nothing is waiting for you right now.")

    analytics = await outreach_analytics(session, user.id, now, days=90)
    if analytics.sent:
        lines += [
            "",
            f"Last 90 days: {_plural(analytics.replied, 'reply', 'replies')} to "
            f"{_plural(analytics.sent, 'email')} ({analytics.reply_rate}%).",
        ]
        lines.append(analytics.verdict)
    quota = await quota_status(session, user.id, now)
    if quota.message:
        lines += ["", quota.message]
    lines += [
        "",
        f"Open your review queue: {get_settings().frontend_url}/review",
        "",
        "You get this every Monday. Turn it off in Sherlock under Settings, Schedule.",
    ]
    subject = f"Sherlock: {_plural(sent + followups, 'email')} sent, {_plural(replies, 'reply', 'replies')}"
    return WeeklySummary(
        subject=subject, body="\n".join(lines), empty=not (sent or followups or replies or pending)
    )


def _local(now: datetime, tz: str) -> datetime:
    try:
        return now.astimezone(ZoneInfo(tz))
    except (ZoneInfoNotFoundError, ValueError):
        return now.astimezone(ZoneInfo("Asia/Kolkata"))


async def users_due_for_summary(session: AsyncSession, redis: Redis, now: datetime) -> list[uuid.UUID]:
    """Active users for whom it's Monday 08:xx local time and this week's summary hasn't been claimed.
    The Redis guard makes the hourly task idempotent: one summary per user per ISO week."""
    due = []
    for user_id, tz in (
        await session.execute(select(User.id, User.timezone).where(User.is_active.is_(True)))
    ).all():
        local = _local(now, tz)
        if local.weekday() != SUMMARY_WEEKDAY or local.hour != SUMMARY_HOUR:
            continue
        year, week, _ = local.isocalendar()
        if await redis.set(f"weekly_summary:{user_id}:{year}-{week}", "1", nx=True, ex=8 * 86400):
            due.append(user_id)
    return due


async def send_summary(session: AsyncSession, user: User, gmail: GmailFactory, now: datetime) -> str:
    """Returns what happened: "sent", "off", "empty", "no_gmail" or "failed"."""
    prefs = await load_preferences(session, user.id)
    if not prefs.weekly_summary:
        return "off"
    token = await get_token_row(session, user.id)
    if token is not None and token.needs_reauth:
        return "no_gmail"
    summary = await build_summary(session, user, now)
    if summary.empty:
        return "empty"
    try:
        client = await gmail(session, user)
    except GmailNotConnectedError:
        return "no_gmail"
    try:
        await client.send(OutgoingEmail(to=user.email, subject=summary.subject, body=summary.body))
    except (GmailError, GoogleAuthError):
        log.warning("weekly summary for user %s not sent", user.id, exc_info=True)
        return "failed"
    return "sent"
