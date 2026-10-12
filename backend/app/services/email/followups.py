"""Follow-ups (PLAN.md Phase 7, §8 `create_followups`).

A sent email with no reply after `followup_after_days` gets one short follow-up draft (≤ 60 words),
which goes through the same review queue; once approved it is sent in the same Gmail thread with no
attachment. Never more than one (`followup_count` ≤ 1, a DB check). If the user's LLM key or quota
stops drafting, the outreach waits in `followup_due` and the next run tries again.
"""

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, Contact, Job, Outreach
from app.models.enums import OutreachEventType, OutreachStatus
from app.schemas.outreach import DraftIssue, EmailDraft
from app.schemas.resume import Basics, MasterResume
from app.services.email.drafter import STYLE_CODES, check_text, compose_body
from app.services.email.state import transition
from app.services.email.style import style_issues
from app.services.llm.client import (
    LLMAuthError,
    LLMClient,
    LLMConfigError,
    LLMOutputError,
    LLMQuotaExhaustedError,
    LLMRateLimitedError,
    metered,
)
from app.services.llm.prompt_loader import load_prompt
from app.services.llm.redaction import redact_pii
from app.services.llm.user_keys import LLMKeyRequiredError, resolve_api_key
from app.services.matching.pipeline import load_preferences
from app.services.resume import store
from app.services.usage import record_llm_usage

log = logging.getLogger(__name__)

S = OutreachStatus
OPERATION = "draft_followup"
MAX_FOLLOWUP_WORDS = 60  # the model's part
MAX_FOLLOWUP_TOTAL = 100  # with greeting and opt-out line


class FollowupBody(BaseModel):
    """LLM contract for prompts/draft_followup.md."""

    body: str


@dataclass
class FollowupSummary:
    drafted: int = 0
    failed: int = 0
    stopped: str | None = None


def followup_subject(subject: str | None) -> str:
    subject = (subject or "").strip()
    return subject if subject.lower().startswith("re:") else f"Re: {subject}"


def validate_followup(subject: str, body: str, composed: str) -> list[DraftIssue]:
    issues = check_text(subject, composed, max_words=MAX_FOLLOWUP_TOTAL)
    words = len(body.split())
    if words > MAX_FOLLOWUP_WORDS:
        issues.append(
            DraftIssue(code="too_long", message=f"{words} words; keep it under {MAX_FOLLOWUP_WORDS}.")
        )
    return issues + style_issues(subject, body, [])


class FollowupDrafter:
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm
        self._prompt = load_prompt("draft_followup")

    async def draft(
        self, outreach: Outreach, contact: Contact, basics: Basics, job_title: str, company: str,
        now: datetime, api_key: str | None,
    ) -> tuple[str, str]:  # fmt: skip
        """(subject, body) of the follow-up. Raises LLMOutputError if two attempts are unusable."""
        days = max(1, (now - (outreach.sent_at or now)).days)
        payload = {
            "original": redact_pii(outreach.body or ""),
            "days_since": days,
            "job_title": job_title,
            "company": company,
            "recipient_role": contact.role_category.value,
        }
        subject = followup_subject(outreach.subject)
        feedback = "(none)"
        issues: list[DraftIssue] = []
        for attempt in (1, 2):
            request = self._prompt.request(
                tier="smart", api_key=api_key, allow_fallback=True, feedback=feedback,
                inputs=json.dumps(payload, ensure_ascii=False, indent=2),
            )  # fmt: skip
            result = await self._llm.generate(request, FollowupBody)
            composed = compose_body(
                EmailDraft(subject=subject, body=result.body, personalization_source=""), contact, basics
            )
            issues = validate_followup(subject, result.body, composed)
            if not issues or (attempt == 2 and all(i.code in STYLE_CODES for i in issues)):
                return subject, composed
            log.info("follow-up attempt %d rejected: %s", attempt, [i.code for i in issues])
            feedback = "\n".join(f"- [{i.code}] {i.message}" for i in issues)
            feedback += f"\n\nYour previous answer: {result.model_dump_json()}"
        raise LLMOutputError("draft_followup", "; ".join(i.message for i in issues))


_PAUSING = (LLMQuotaExhaustedError, LLMRateLimitedError, LLMAuthError, LLMConfigError, LLMKeyRequiredError)


class Followups:
    def __init__(self, llm: LLMClient) -> None:
        self._drafter = FollowupDrafter(llm)

    async def run_for_user(
        self, session: AsyncSession, user_id: uuid.UUID, now: datetime | None = None
    ) -> FollowupSummary:
        now = now or datetime.now(UTC)
        summary = FollowupSummary()
        prefs = await load_preferences(session, user_id)
        if prefs.paused:
            summary.stopped = "paused"
            return summary
        due_before = now - timedelta(days=prefs.followup_after_days)
        rows = (
            await session.scalars(
                select(Outreach).where(
                    Outreach.user_id == user_id,
                    Outreach.followup_count == 0,
                    Outreach.replied_at.is_(None),
                    or_(
                        (Outreach.status == S.SENT) & (Outreach.sent_at <= due_before),
                        Outreach.status == S.FOLLOWUP_DUE,
                    ),
                )
            )
        ).all()
        if not rows:
            return summary
        resume_row = await store.get_current(session, user_id)
        basics = MasterResume.model_validate(resume_row.data).basics if resume_row else Basics(name="")
        for outreach in rows:
            if outreach.status == S.SENT:
                await transition(session, outreach, S.FOLLOWUP_DUE, actor_id=None, payload={"due": True})
                await session.commit()
            contact = await session.get(Contact, outreach.contact_id) if outreach.contact_id else None
            if contact is None:
                continue
            job = await session.get(Job, outreach.job_id) if outreach.job_id else None
            company = await session.get(Company, outreach.company_id)
            with metered() as meter:
                try:
                    api_key = await resolve_api_key(session, user_id)
                    subject, body = await self._drafter.draft(
                        outreach, contact, basics, job.title if job else "the role",
                        company.name if company else "", now, api_key,
                    )  # fmt: skip
                except _PAUSING as exc:
                    summary.stopped = type(exc).__name__
                    await record_llm_usage(session, user_id, OPERATION, meter.calls)
                    await session.commit()
                    break
                except LLMOutputError as exc:
                    log.info("follow-up for %s not drafted: %s", outreach.id, exc)
                    summary.failed += 1
                    await record_llm_usage(session, user_id, OPERATION, meter.calls)
                    await session.commit()
                    continue  # stays followup_due; the user can still close it from the tracker
                await record_llm_usage(session, user_id, OPERATION, meter.calls)
            original = {"subject": outreach.subject, "body": outreach.body}
            outreach.subject, outreach.body = subject, body
            outreach.followup_count = 1
            await transition(
                session, outreach, S.PENDING_REVIEW, actor_id=None, event=OutreachEventType.FOLLOWUP_DRAFTED,
                payload={"original": original},
            )  # fmt: skip
            await session.commit()
            summary.drafted += 1
        return summary
