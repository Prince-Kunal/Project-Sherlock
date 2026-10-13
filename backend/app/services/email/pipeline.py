"""The draft pipeline (PLAN.md Phase 6): contact (Phase 5) → tailor (Phase 4) → draft → pending_review. Open
outreach (Phase 8) runs the same steps from a company match instead of a job: contact titles from the
prospect target, a resume tailored to a synthetic brief, and an email hooked on the company's own text
that never implies an opening.

Shared by the daily `build_daily_drafts` task, the "Draft now" buttons on job and company matches and
"Retry" on a failed outreach. The daily batch is split between job matches and company matches by
`open_outreach_share`; when one side runs short, the other fills the gap (§8). A step that fails moves
that outreach to `failed` with a reason and the batch goes on with the next one. When the user's LLM
quota or key is the problem, nothing is failed: the outreach stays in `drafting` and
`DraftingPausedError` stops the run, so the next run resumes it (the Hunter credit already spent on its
contact isn't wasted).
"""

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from redis.asyncio import Redis
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging import log_context
from app.models import (
    Company,
    CompanyMatch,
    Contact,
    Job,
    JobMatch,
    Outreach,
    ProspectTarget,
    User,
    UserCompanyBlock,
)
from app.models.enums import (
    INACTIVE_OUTREACH_STATUSES,
    CampaignType,
    CompanyMatchStatus,
    JobMatchStatus,
    OutreachStatus,
)
from app.schemas.resume import MasterResume
from app.services.contacts.service import (
    OutreachConflictError,
    ProviderFactory,
    build_finder,
    find_contact_for,
    start_job_outreach,
    start_open_outreach,
)
from app.services.email.drafter import (
    Drafter,
    DraftError,
    DraftInputs,
    OpenDraftInputs,
    research_sentences,
)
from app.services.email.state import transition
from app.services.email.variants import choose_variant
from app.services.llm.client import (
    LLMAuthError,
    LLMClient,
    LLMConfigError,
    LLMOutputError,
    LLMQuotaExhaustedError,
    LLMRateLimitedError,
    metered,
)
from app.services.llm.user_keys import LLMKeyRequiredError, resolve_api_key
from app.services.matching.filters import hard_filter_conditions
from app.services.matching.pipeline import load_preferences
from app.services.prospects.website import WebsiteFetcher
from app.services.quotas import over_quota
from app.services.resume import store
from app.services.resume.files import find_pdf, save_tailored_pdf
from app.services.resume.skills import get_lexicon
from app.services.resume.tailor import OpenBrief, Tailor, TailorError, TailorResult
from app.services.resume.validator import master_skill_set
from app.services.usage import record_llm_usage

log = logging.getLogger(__name__)

TAILOR_OPERATION = "tailor_resume"
DRAFT_OPERATION = "draft_email"
RECENTLY_SENT_DAYS = 90  # don't start a new outreach to a company this user emailed recently

# The LLM problems that pause a user's drafting instead of failing the job.
_PAUSING = (LLMQuotaExhaustedError, LLMRateLimitedError, LLMAuthError, LLMConfigError, LLMKeyRequiredError)


class DraftingPausedError(Exception):
    """The user's LLM key or quota stops drafting for now; `cause` is the original LLM error."""

    def __init__(self, cause: Exception) -> None:
        super().__init__(type(cause).__name__)
        self.cause = cause


@dataclass
class BuildSummary:
    drafted: int = 0
    failed: int = 0
    skipped_conflicts: int = 0
    stopped: str | None = None  # why the run ended early, if it did
    planned_job: int = 0  # new outreach started from job matches this run
    planned_open: int = 0  # ... and from company matches

    def as_dict(self) -> dict[str, Any]:
        return {"drafted": self.drafted, "failed": self.failed, "stopped": self.stopped}


def split_batch(room: int, share: int, jobs_available: int, open_available: int) -> tuple[int, int]:
    """(job, open) counts for `room` new drafts: `share`% open outreach, rounded, and when one side
    has fewer candidates than its share the other fills the gap (PLAN.md §8)."""
    want_open = round(room * share / 100)
    take_open = min(want_open, open_available)
    take_job = min(room - take_open, jobs_available)
    take_open = min(room - take_job, open_available)
    return take_job, take_open


@dataclass
class BuildAllSummary:
    users: int = 0
    drafted: int = 0
    failed: int = 0
    stopped: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, int]:
        return {
            "users": self.users,
            "drafted": self.drafted,
            "failed": self.failed,
            "stopped": len(self.stopped),
        }


@asynccontextmanager
async def _llm_step(session: AsyncSession, user_id: uuid.UUID, operation: str) -> AsyncIterator[None]:
    """Log the step's LLM calls (also when it fails) and turn key/quota errors into a pause."""
    with metered() as meter:
        try:
            yield
        except _PAUSING as exc:
            raise DraftingPausedError(exc) from exc
        finally:
            await record_llm_usage(session, user_id, operation, meter.calls)


def tailored_record(result: TailorResult, version: int) -> dict[str, Any]:
    """What's kept on the outreach row: the tailored resume, its order and ranking (for highlights)."""
    return {
        "resume_version": version,
        "resume": result.resume.model_dump(mode="json"),
        "section_order": list(result.section_order),
        "ranking": result.plan.selected_bullet_ids,
        "filename": result.filename,
        "ats": result.ats.model_dump(mode="json"),
        "dropped_to_fit": result.dropped_to_fit,
    }


def highlights(record: dict[str, Any], limit: int = 2) -> list[str]:
    resume = MasterResume.model_validate(record["resume"])
    texts = {b.id: b.text for b in resume.all_bullets()}
    return [texts[i] for i in record.get("ranking", []) if i in texts][:limit]


class DraftPipeline:
    def __init__(
        self,
        llm: LLMClient,
        factory: ProviderFactory,
        now: datetime | None = None,
        *,
        apollo_factory: ProviderFactory | None = None,
        fetcher: WebsiteFetcher | None = None,
    ) -> None:
        """`apollo_factory` adds Apollo before Hunter for users with an Apollo key; `fetcher` reads a
        company's website on demand when open outreach has no company text to quote yet."""
        self._llm = llm
        self._factory = factory
        self._apollo_factory = apollo_factory
        self._fetcher = fetcher
        self._now = now
        self._lexicon = get_lexicon()
        self._tailor = Tailor(llm, self._lexicon)
        self._drafter = Drafter(llm, self._lexicon)

    def now(self) -> datetime:
        return self._now or datetime.now(UTC)

    async def _fail(
        self, session: AsyncSession, outreach: Outreach, reason: str, message: str, actor_id: uuid.UUID | None
    ) -> None:
        await transition(
            session, outreach, OutreachStatus.FAILED, actor_id=actor_id, failure_reason=reason,
            payload={"message": message[:500]},
        )  # fmt: skip

    async def run(self, session: AsyncSession, outreach: Outreach, *, actor_id: uuid.UUID | None) -> None:
        """Take one outreach in `drafting` to `pending_review` or `failed`. Raises DraftingPausedError
        (outreach left in `drafting`) when the user's LLM key or quota stops it. Caller commits."""
        with log_context(user_id=outreach.user_id, outreach_id=outreach.id):
            await self._run(session, outreach, actor_id=actor_id)

    async def _run(self, session: AsyncSession, outreach: Outreach, *, actor_id: uuid.UUID | None) -> None:
        if outreach.status != OutreachStatus.DRAFTING:
            raise ValueError(f"outreach {outreach.id} is {outreach.status.value}, not drafting")
        user_id = outreach.user_id
        job = await session.get(Job, outreach.job_id) if outreach.job_id else None
        company = await session.get(Company, outreach.company_id)
        is_open = outreach.campaign_type == CampaignType.OPEN
        match, target = await self._company_match(session, outreach) if is_open else (None, None)
        if company is None or (job is None and not is_open) or (is_open and match is None):
            await self._fail(
                session, outreach, "missing_inputs", "Its job or company match no longer exists.", actor_id
            )
            return
        if is_open and not await self._has_company_text(session, company):
            await self._fail(
                session, outreach, "no_company_context",
                f"There's no description or website text for {company.name} to base the email on.",
                actor_id,
            )  # fmt: skip
            return
        resume_row = await store.get_current(session, user_id)
        if resume_row is None:
            await self._fail(session, outreach, "no_resume", "Upload your resume first.", actor_id)
            return
        master = MasterResume.model_validate(resume_row.data)
        try:
            api_key = await resolve_api_key(session, user_id)
        except LLMKeyRequiredError as exc:
            raise DraftingPausedError(exc) from exc

        finder = await build_finder(
            session, user_id, self._factory, self.now(), apollo_factory=self._apollo_factory
        )
        titles = list(target.contact_titles) if target else []
        contact = await find_contact_for(
            session, outreach, job, company, finder, actor_id=actor_id, titles=titles
        )
        if contact is None:
            return  # failed with the contact step's reason

        record = outreach.tailored_resume
        pdf = find_pdf(user_id, str(outreach.id)) if record else None
        if record is None or pdf is None or record.get("resume_version") != resume_row.version:
            try:
                async with _llm_step(session, user_id, TAILOR_OPERATION):
                    if job is not None:
                        result = await self._tailor.tailor(master, job, company, api_key)
                    else:
                        brief = await self._brief(session, outreach.user_id, company, match, target)
                        result = await self._tailor.tailor_open(master, brief, api_key)
            except TailorError as exc:
                details = "; ".join(i.message for i in exc.issues[:3]) or str(exc)
                await self._fail(session, outreach, exc.reason, details, actor_id)
                return
            except LLMOutputError as exc:
                await self._fail(session, outreach, "llm_output_invalid", str(exc), actor_id)
                return
            pdf = await save_tailored_pdf(user_id, str(outreach.id), result.filename, result.rendered.pdf)
            record = tailored_record(result, resume_row.version)
            outreach.tailored_resume = record
            outreach.resume_pdf_path = str(pdf)
            outreach.resume_diff = [c.model_dump(mode="json") for c in result.diff]
            outreach.ats_keyword_coverage = result.keyword_coverage.model_dump(mode="json")
            await session.flush()

        if outreach.draft_variant is None:
            prefs = await load_preferences(session, user_id)
            outreach.draft_variant = await choose_variant(session, user_id, prefs.draft_style)
            await session.flush()
        try:
            async with _llm_step(session, user_id, DRAFT_OPERATION):
                if job is not None:
                    inputs = await self._draft_inputs(session, outreach, job, company, contact, master)
                    draft = await self._drafter.draft(inputs, api_key)
                else:
                    open_inputs = await self._open_draft_inputs(
                        session, outreach, company, contact, master, match, target
                    )
                    draft = await self._drafter.draft_open(open_inputs, api_key)
        except DraftError as exc:
            await self._fail(
                session, outreach, exc.reason, "; ".join(i.message for i in exc.issues), actor_id
            )
            return
        except LLMOutputError as exc:
            await self._fail(session, outreach, "llm_output_invalid", str(exc), actor_id)
            return
        outreach.subject = draft.subject
        outreach.body = draft.body
        outreach.personalization_source = draft.personalization_source
        await transition(
            session,
            outreach,
            OutreachStatus.PENDING_REVIEW,
            actor_id=actor_id,
            payload={"subject": draft.subject},
        )

    async def _company_match(
        self, session: AsyncSession, outreach: Outreach
    ) -> tuple[CompanyMatch | None, ProspectTarget | None]:
        match = (
            await session.get(CompanyMatch, outreach.company_match_id) if outreach.company_match_id else None
        )
        target = (
            await session.get(ProspectTarget, match.prospect_target_id)
            if match and match.prospect_target_id
            else None
        )
        return match, target

    async def _has_company_text(self, session: AsyncSession, company: Company) -> bool:
        """Open outreach quotes the company's own text; read its website now if there's none yet."""
        if company.description or company.website_text:
            return True
        return await self._read_website(session, company)

    async def _read_website(self, session: AsyncSession, company: Company) -> bool:
        """Fetch the company's site once (home, about, careers, latest blog post) if never tried."""
        if company.website_text:
            return True
        if self._fetcher is None or not company.domain or company.website_fetched_at is not None:
            return False
        text = await self._fetcher.fetch(company.domain)
        company.website_fetched_at = self.now()
        if text:
            company.website_text = text
            company.embedding = None
        await session.flush()
        return bool(text)

    async def _brief(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        company: Company,
        match: CompanyMatch | None,
        target: ProspectTarget | None,
    ) -> OpenBrief:
        prefs = await load_preferences(session, user_id)
        about = "\n".join(p for p in (company.description, company.website_text) if p)
        return OpenBrief(
            company=company.name,
            target_roles=list(target.target_roles if target and target.target_roles else prefs.target_roles),
            about=about,
            angle=match.angle if match else "",
        )

    async def _open_draft_inputs(
        self,
        session: AsyncSession,
        outreach: Outreach,
        company: Company,
        contact: Contact,
        master: MasterResume,
        match: CompanyMatch | None,
        target: ProspectTarget | None,
        hint: str | None = None,
    ) -> OpenDraftInputs:
        prefs = await load_preferences(session, outreach.user_id)
        return OpenDraftInputs(
            company=company,
            contact=contact,
            basics=master.basics,
            about_me=prefs.about_me,
            highlights=highlights(outreach.tailored_resume or {}),
            skills=master_skill_set(master, self._lexicon),
            variant=outreach.draft_variant or "a",
            angle=match.angle if match else "",
            target_roles=list(target.target_roles if target and target.target_roles else prefs.target_roles),
            employment_types=list(prefs.employment_types),
            hint=hint,
        )

    async def _draft_inputs(
        self,
        session: AsyncSession,
        outreach: Outreach,
        job: Job,
        company: Company,
        contact: Contact,
        master: MasterResume,
        hint: str | None = None,
    ) -> DraftInputs:
        prefs = await load_preferences(session, outreach.user_id)
        skills = master_skill_set(master, self._lexicon)
        # Phase 10: a line or two from the company's own site or latest blog post, as hook candidates.
        await self._read_website(session, company)
        return DraftInputs(
            job=job,
            company=company,
            contact=contact,
            basics=master.basics,
            about_me=prefs.about_me,
            highlights=highlights(outreach.tailored_resume or {}),
            skills=skills,
            hint=hint,
            variant=outreach.draft_variant or "a",
            research=research_sentences(company, skills, self._lexicon),
        )

    async def regenerate(
        self, session: AsyncSession, outreach: Outreach, *, hint: str | None, api_key: str | None
    ) -> tuple[str, str, str]:
        """A new email for a draft in review (the tailored resume is kept). Raises DraftError or LLM
        errors; the caller records the event and commits."""
        job = await session.get(Job, outreach.job_id) if outreach.job_id else None
        company = await session.get(Company, outreach.company_id)
        contact = await session.get(Contact, outreach.contact_id) if outreach.contact_id else None
        resume_row = await store.get_current(session, outreach.user_id)
        is_open = outreach.campaign_type == CampaignType.OPEN
        if (job is None and not is_open) or company is None or contact is None or resume_row is None:
            raise DraftError("missing_inputs", "This draft is missing its job, contact or resume.")
        master = MasterResume.model_validate(resume_row.data)
        with metered() as meter:
            try:
                if job is not None:
                    inputs = await self._draft_inputs(session, outreach, job, company, contact, master, hint)
                    draft = await self._drafter.draft(inputs, api_key)
                else:
                    match, target = await self._company_match(session, outreach)
                    open_inputs = await self._open_draft_inputs(
                        session, outreach, company, contact, master, match, target, hint
                    )
                    draft = await self._drafter.draft_open(open_inputs, api_key)
            finally:
                await record_llm_usage(session, outreach.user_id, DRAFT_OPERATION, meter.calls)
        return draft.subject, draft.body, draft.personalization_source

    # --- The daily batch ---------------------------------------------------------------------------

    def _busy_companies(self, user_id: uuid.UUID) -> Any:
        """Companies with an active outreach (invariant 4) or one emailed in the last 90 days."""
        return select(Outreach.company_id).where(
            Outreach.user_id == user_id,
            or_(
                Outreach.status.not_in(INACTIVE_OUTREACH_STATUSES),
                Outreach.sent_at >= self.now() - timedelta(days=RECENTLY_SENT_DAYS),
            ),
        )

    async def _candidates(
        self, session: AsyncSession, user_id: uuid.UUID, limit: int
    ) -> list[tuple[JobMatch, Job]]:
        """The user's best undrafted job matches, shortlisted first, one per company, skipping busy
        companies."""
        prefs = await load_preferences(session, user_id)
        rows = (
            await session.execute(
                select(JobMatch, Job)
                .join(Job, Job.id == JobMatch.job_id)
                .where(
                    JobMatch.user_id == user_id,
                    JobMatch.status.in_([JobMatchStatus.NEW, JobMatchStatus.SHORTLISTED]),
                    JobMatch.llm_score >= prefs.min_fit_score,
                    Job.company_id.not_in(self._busy_companies(user_id)),
                    *hard_filter_conditions(
                        user_id,
                        max_job_age_days=prefs.max_job_age_days,
                        employment_types=list(prefs.employment_types),
                        company_stages=list(prefs.company_stages),
                        job_sources=list(prefs.job_sources),
                        now=self.now(),
                    ),
                )
                .order_by(
                    (JobMatch.status == JobMatchStatus.SHORTLISTED).desc(),
                    JobMatch.llm_score.desc(),
                    JobMatch.created_at,
                )
                .limit(limit * 5)
            )
        ).all()
        chosen: list[tuple[JobMatch, Job]] = []
        companies: set[uuid.UUID] = set()
        for match, job in rows:
            if job.company_id not in companies:
                companies.add(job.company_id)
                chosen.append((match, job))
        return chosen[:limit]

    async def _company_candidates(
        self, session: AsyncSession, user_id: uuid.UUID, limit: int
    ) -> list[CompanyMatch]:
        """The user's best company matches for open outreach: queued first, then by score, from
        active targets, skipping busy and blocked companies."""
        if limit <= 0:
            return []
        prefs = await load_preferences(session, user_id)
        blocked = select(UserCompanyBlock.company_id).where(UserCompanyBlock.user_id == user_id)
        return list(
            (
                await session.scalars(
                    select(CompanyMatch)
                    .join(ProspectTarget, ProspectTarget.id == CompanyMatch.prospect_target_id)
                    .where(
                        CompanyMatch.user_id == user_id,
                        ProspectTarget.is_active.is_(True),
                        CompanyMatch.status.in_([CompanyMatchStatus.NEW, CompanyMatchStatus.QUEUED]),
                        CompanyMatch.score >= prefs.min_fit_score,
                        CompanyMatch.company_id.not_in(self._busy_companies(user_id)),
                        CompanyMatch.company_id.not_in(blocked),
                    )
                    .order_by(
                        (CompanyMatch.status == CompanyMatchStatus.QUEUED).desc(),
                        CompanyMatch.score.desc(),
                        CompanyMatch.created_at,
                    )
                    .limit(limit)
                )
            ).all()
        )

    async def plan_batch(
        self, session: AsyncSession, user_id: uuid.UUID, room: int
    ) -> list[tuple[JobMatch, Job] | CompanyMatch]:
        """Up to `room` new items, split by `open_outreach_share` (the other side fills a gap), never
        two for the same company, alternating so a run cut short still covers both modes."""
        if room <= 0:
            return []
        prefs = await load_preferences(session, user_id)
        jobs = await self._candidates(session, user_id, room)
        job_companies = {job.company_id for _, job in jobs}
        companies = [
            c
            for c in await self._company_candidates(session, user_id, room + len(jobs))
            if c.company_id not in job_companies
        ]
        take_job, take_open = split_batch(room, prefs.open_outreach_share, len(jobs), len(companies))
        picked_jobs: list[tuple[JobMatch, Job] | CompanyMatch] = list(jobs[:take_job])
        picked_open: list[tuple[JobMatch, Job] | CompanyMatch] = list(companies[:take_open])
        plan: list[tuple[JobMatch, Job] | CompanyMatch] = []
        for i in range(max(len(picked_jobs), len(picked_open))):
            plan += [*picked_jobs[i : i + 1], *picked_open[i : i + 1]]
        return plan

    async def build_for_user(self, session: AsyncSession, user_id: uuid.UUID) -> BuildSummary:
        """Fill the user's review queue up to `daily_draft_batch`: first resume outreach left in
        `drafting`, then start new ones from the best job and company matches. Commits after every
        item."""
        summary = BuildSummary()
        prefs = await load_preferences(session, user_id)
        if prefs.paused:
            summary.stopped = "paused"
            return summary
        if await over_quota(session, user_id, self.now()):
            summary.stopped = "quota_exceeded"
            return summary
        if await store.get_current(session, user_id) is None:
            summary.stopped = "no_resume"
            return summary
        try:
            await resolve_api_key(session, user_id)
        except LLMKeyRequiredError:
            summary.stopped = "no_llm_key"
            return summary
        pending = await session.scalar(
            select(func.count()).where(
                Outreach.user_id == user_id, Outreach.status == OutreachStatus.PENDING_REVIEW
            )
        )
        room = prefs.daily_draft_batch - int(pending or 0)
        if room <= 0:
            return summary

        resumable = list(
            (
                await session.scalars(
                    select(Outreach)
                    .where(Outreach.user_id == user_id, Outreach.status == OutreachStatus.DRAFTING)
                    .order_by(Outreach.created_at)
                    .limit(room)
                )
            ).all()
        )
        queue: list[Outreach | tuple[JobMatch, Job] | CompanyMatch] = [*resumable]
        planned = await self.plan_batch(session, user_id, room - len(queue))
        summary.planned_job = sum(1 for item in planned if isinstance(item, tuple))
        summary.planned_open = len(planned) - summary.planned_job
        queue += planned

        for item in queue:
            if isinstance(item, Outreach):
                outreach = item
            else:
                try:
                    if isinstance(item, CompanyMatch):
                        outreach = await start_open_outreach(session, user_id, item)
                    else:
                        outreach = await start_job_outreach(session, user_id, *item)
                except OutreachConflictError:
                    await session.rollback()
                    summary.skipped_conflicts += 1
                    continue
                await session.commit()
            try:
                await self.run(session, outreach, actor_id=None)
            except DraftingPausedError as exc:
                await session.commit()  # keep the usage rows and the contact found
                summary.stopped = type(exc.cause).__name__
                break
            await session.commit()
            if outreach.status == OutreachStatus.PENDING_REVIEW:
                summary.drafted += 1
            else:
                summary.failed += 1
        return summary

    async def build_all(
        self, sessions: async_sessionmaker[AsyncSession], user_ids: list[uuid.UUID] | None = None
    ) -> BuildAllSummary:
        total = BuildAllSummary()
        async with sessions() as session:
            if user_ids is None:
                user_ids = list(
                    (await session.scalars(select(User.id).where(User.is_active.is_(True)))).all()
                )
        for user_id in user_ids:
            with log_context(user_id=user_id):
                async with sessions() as session:
                    try:
                        summary = await self.build_for_user(session, user_id)
                    except Exception:  # one user's failure must not stop the others
                        log.exception("build_daily_drafts failed for user %s", user_id)
                        total.stopped[str(user_id)] = "error"
                        continue
                total.users += 1
                total.drafted += summary.drafted
                total.failed += summary.failed
                if summary.stopped:
                    total.stopped[str(user_id)] = summary.stopped
        return total


def pdf_for(outreach: Outreach) -> Path | None:
    return find_pdf(outreach.user_id, str(outreach.id))


DAILY_DRAFT_HOUR = 7  # PLAN.md §8: build_daily_drafts runs at 07:00 in each user's timezone


async def users_due_for_drafts(
    session: AsyncSession,
    redis: Redis,
    now: datetime,
    hour: int = DAILY_DRAFT_HOUR,
    job: str = "drafts_built",
) -> list[uuid.UUID]:
    """Active users for whom it is now `hour` o'clock local time and today's `job` hasn't run yet.
    The Redis guard makes an hourly task idempotent: one automatic run per user per local day."""
    due = []
    for user_id, tz in (
        await session.execute(select(User.id, User.timezone).where(User.is_active.is_(True)))
    ).all():
        try:
            local = now.astimezone(ZoneInfo(tz))
        except (ZoneInfoNotFoundError, ValueError):
            local = now.astimezone(ZoneInfo("Asia/Kolkata"))
        if local.hour != hour:
            continue
        if await redis.set(f"{job}:{user_id}:{local.date().isoformat()}", "1", nx=True, ex=2 * 86400):
            due.append(user_id)
    return due
