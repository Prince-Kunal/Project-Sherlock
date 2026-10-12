"""Reply tracking (PLAN.md Phase 7, §8 `check_replies`).

For every sent thread, new messages from someone else are classified:

- a bounce (Mailer-Daemon / postmaster / "Delivery Status Notification") → the contact becomes
  `invalid`, the address is suppressed (`bounce`) and the outreach `failed`;
- an opt-out ("unsubscribe", "don't contact", "not interested", "remove me", …) → suppressed
  (`opt_out`) and the outreach `replied` then `closed` (invariant 9);
- anything else → `replied`, which also cancels a follow-up still being reviewed or scheduled.

Automatic replies (out of office) are ignored. Quoted text is stripped before classifying, so our
own email quoted underneath a reply can't trigger anything. Only ambiguous wording ("no thanks",
"please stop") is sent to the fast LLM as a tiebreaker; if that isn't possible the reply is treated
as an opt-out, the safer side for the recipient.
"""

import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Contact, Outreach, SuppressionEntry, User
from app.models.enums import OutreachEventType, OutreachStatus, SuppressionReason, VerificationStatus
from app.services.email.connection import GmailFactory, mark_needs_reauth
from app.services.email.gmail import GmailError, GmailNotConnectedError, ThreadMessage
from app.services.email.state import can_transition, record_event, transition
from app.services.google.oauth import GoogleReauthRequiredError
from app.services.llm.client import LLMClient, LLMError
from app.services.llm.prompt_loader import load_prompt
from app.services.llm.redaction import redact_pii
from app.services.llm.user_keys import LLMKeyRequiredError, resolve_api_key
from app.services.usage import record_llm_usage

log = logging.getLogger(__name__)

S = OutreachStatus
# Outreach whose thread is watched: sent, waiting for a follow-up, or with a follow-up in progress.
WATCHED = (S.SENT, S.FOLLOWUP_DUE, S.PENDING_REVIEW, S.APPROVED, S.SCHEDULED)
CLASSIFY_OPERATION = "classify_reply"

_BOUNCE_FROM_RE = re.compile(r"^(?:mailer-daemon|postmaster|mail-daemon)@", re.I)
_BOUNCE_SUBJECT_RE = re.compile(
    r"delivery status notification|undeliverable|undelivered mail|mail delivery (?:failed|failure|subsystem)|"
    r"returned mail|delivery (?:has )?failed|address not found",
    re.I,
)
_OPT_OUT_RE = re.compile(
    r"unsubscribe|do(?:n'?t| not) (?:contact|email|e-mail|message|reach out to) me|not interested|"
    r"remove me|take me off|stop (?:emailing|contacting|messaging) me|don'?t email me again",
    re.I,
)
_MAYBE_OPT_OUT_RE = re.compile(r"\bno,? thank(?:s| you)\b|\bplease stop\b|\bstop\b|\bleave me alone\b", re.I)
# Where the quoted original starts in a plain-text reply.
_QUOTE_START_RE = re.compile(
    r"^(?:On .{5,200}wrote:\s*$|-{2,} ?Original Message ?-{2,}|From: .+$|_{10,})", re.I | re.M
)


class ReplyIntent(BaseModel):
    """LLM contract for prompts/classify_reply.md."""

    intent: Literal["opt_out", "reply"]


def strip_quoted(body: str) -> str:
    """The new text of a reply: everything above the quoted original, minus '>' lines."""
    match = _QUOTE_START_RE.search(body)
    text = body[: match.start()] if match else body
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(">")).strip()


def is_bounce(message: ThreadMessage) -> bool:
    return bool(_BOUNCE_FROM_RE.match(message.from_address) or _BOUNCE_SUBJECT_RE.search(message.subject))


Kind = Literal["bounce", "opt_out", "maybe_opt_out", "reply"]


def classify(message: ThreadMessage) -> Kind:
    if is_bounce(message):
        return "bounce"
    text = strip_quoted(message.body) or message.snippet
    if _OPT_OUT_RE.search(text):
        return "opt_out"
    if _MAYBE_OPT_OUT_RE.search(text):
        return "maybe_opt_out"
    return "reply"


@dataclass
class ReplySummary:
    checked: int = 0
    replied: int = 0
    opted_out: int = 0
    bounced: int = 0
    errors: int = 0
    stopped: str | None = None
    by_outreach: dict[str, str] = field(default_factory=dict)


async def _suppress(session: AsyncSession, email: str, reason: SuppressionReason) -> None:
    exists = await session.scalar(
        select(SuppressionEntry.id).where(func.lower(SuppressionEntry.email) == email.lower())
    )
    if exists is None:
        session.add(SuppressionEntry(email=email.lower(), reason=reason))
        await session.flush()


class ReplyChecker:
    def __init__(self, gmail: GmailFactory, llm: LLMClient | None) -> None:
        self._gmail = gmail
        self._llm = llm

    async def _tiebreak(self, session: AsyncSession, user_id: uuid.UUID, text: str) -> Kind:
        if self._llm is None:
            return "opt_out"
        try:
            api_key = await resolve_api_key(session, user_id)
            prompt = load_prompt("classify_reply")
            request = prompt.request(tier="fast", api_key=api_key, reply=redact_pii(text[:2000]))
            result = await self._llm.generate(request, ReplyIntent)
            await record_llm_usage(session, user_id, CLASSIFY_OPERATION, 1)
        except (LLMError, LLMKeyRequiredError) as exc:
            log.info("reply tiebreak unavailable (%s); treating as opt-out", type(exc).__name__)
            return "opt_out"
        return result.intent

    async def check_outreach(
        self, session: AsyncSession, user: User, outreach: Outreach, messages: list[ThreadMessage]
    ) -> str | None:
        """Apply the first new message from someone else. Returns what was detected. Caller commits."""
        since = (outreach.sent_at or datetime.min.replace(tzinfo=UTC)) - timedelta(minutes=1)
        others = [
            m
            for m in messages
            if m.from_address
            and m.from_address != user.email.lower()
            and m.sent_at >= since
            and not m.auto_submitted
        ]
        if not others:
            return None
        message = others[0]
        kind = classify(message)
        text = strip_quoted(message.body) or message.snippet
        if kind == "maybe_opt_out":
            kind = await self._tiebreak(session, user.id, text)
        contact = await session.get(Contact, outreach.contact_id) if outreach.contact_id else None
        detail = {
            "message_id": message.message_id,
            "sender": message.from_address,
            "snippet": (message.snippet or text)[:300],
            "text": text[:2000],
            "received_at": message.sent_at.isoformat(),
        }

        if kind == "bounce":
            if contact is not None:
                contact.verification_status = VerificationStatus.INVALID
                await _suppress(session, contact.email, SuppressionReason.BOUNCE)
            await record_event(session, outreach, OutreachEventType.BOUNCED, detail)
            if can_transition(outreach.status, S.FAILED):
                await transition(
                    session, outreach, S.FAILED, actor_id=None, failure_reason="bounced",
                    payload={"message": "The email bounced; the address doesn't work."},
                )  # fmt: skip
            return "bounce"

        outreach.replied_at = message.sent_at
        await transition(session, outreach, S.REPLIED, actor_id=None, payload=detail)
        if kind == "opt_out":
            if contact is not None:
                await _suppress(session, contact.email, SuppressionReason.OPT_OUT)
            await transition(session, outreach, S.CLOSED, actor_id=None, payload={"reason": "opt_out"})
            return "opt_out"
        return "reply"

    async def run_for_user(self, session: AsyncSession, user: User) -> ReplySummary:
        summary = ReplySummary()
        rows = (
            await session.scalars(
                select(Outreach).where(
                    Outreach.user_id == user.id,
                    Outreach.status.in_(WATCHED),
                    Outreach.gmail_thread_id.is_not(None),
                )
            )
        ).all()
        if not rows:
            return summary
        try:
            gmail = await self._gmail(session, user)
        except GmailNotConnectedError:
            summary.stopped = "not_connected"
            return summary
        for outreach in rows:
            summary.checked += 1
            try:
                messages = await gmail.get_thread(outreach.gmail_thread_id)  # type: ignore[arg-type]
            except GoogleReauthRequiredError:
                await mark_needs_reauth(session, user.id)
                await session.commit()
                summary.stopped = "needs_reauth"
                break
            except GmailError as exc:
                log.warning("check_replies: thread %s: %s", outreach.gmail_thread_id, exc)
                summary.errors += 1
                continue
            found = await self.check_outreach(session, user, outreach, messages)
            await session.commit()
            if found:
                summary.by_outreach[str(outreach.id)] = found
                if found == "reply":
                    summary.replied += 1
                elif found == "opt_out":
                    summary.opted_out += 1
                else:
                    summary.bounced += 1
        return summary
