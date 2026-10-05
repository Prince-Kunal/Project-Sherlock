"""Per-user matching (PLAN.md Phase 3): hard filters → embedding prefilter → LLM rerank → job_matches.

Incremental: a (user, job) pair that already has a job_matches row is never scored again. Scoring uses
the user's own key under a daily allowance of fast-model requests (`MATCH_DAILY_LLM_CALLS`); jobs
not reached stay unscored and are picked up by the next run.
"""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy import ColumnElement, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.models import Company, Job, JobMatch, User, UserPreferences
from app.models import MasterResume as MasterResumeRow
from app.models.enums import JobMatchStatus
from app.schemas.preferences import PreferencesBase
from app.schemas.resume import MasterResume
from app.services.embeddings.embedder import Embedder
from app.services.llm.client import (
    LLMAuthError,
    LLMClient,
    LLMConfigError,
    LLMQuotaExhaustedError,
    LLMRateLimitedError,
    metered,
)
from app.services.llm.user_keys import LLMKeyRequiredError, resolve_api_key
from app.services.matching.embed import DEFAULT_MAX_AGE_DAYS, embed_missing_jobs, user_embedding
from app.services.matching.filters import effective_date, filter_locations, hard_filter_conditions
from app.services.matching.profile import candidate_payload, profile_text, user_skills
from app.services.matching.rerank import Reranker, clean_skills, job_ref
from app.services.resume import store
from app.services.usage import llm_calls_since, record_llm_usage

log = logging.getLogger(__name__)

OPERATION = "match_jobs"
UNSCORABLE_REASON = "Sherlock couldn't score this job automatically."
_CONCRETE_TYPES = {"internship", "full_time", "contract"}


@dataclass
class UserMatchSummary:
    candidates: int = 0  # after hard filters + prefilter
    scored: int = 0
    unscorable: int = 0
    llm_calls: int = 0
    stopped: str | None = None  # why scoring stopped early, if it did


@dataclass
class MatchRunSummary:
    users: int = 0
    scored: int = 0
    llm_calls: int = 0
    stopped: dict[str, str] = field(default_factory=dict)  # user id → reason

    def as_dict(self) -> dict[str, int]:
        return {
            "users": self.users,
            "scored": self.scored,
            "llm_calls": self.llm_calls,
            "stopped": len(self.stopped),
        }


async def load_preferences(session: AsyncSession, user_id: uuid.UUID) -> PreferencesBase:
    row = await session.scalar(select(UserPreferences).where(UserPreferences.user_id == user_id))
    if row is None:
        return PreferencesBase()
    return PreferencesBase.model_validate(row, from_attributes=True)


def daily_window_start(now: datetime) -> datetime:
    return now - timedelta(hours=24)


def _already_matched(user_id: uuid.UUID) -> ColumnElement[bool]:
    return exists().where(JobMatch.user_id == user_id, JobMatch.job_id == Job.id)


class Matcher:
    def __init__(self, *, llm: LLMClient, embedder: Embedder, redis: Redis, settings: Settings) -> None:
        self._llm = llm
        self._embedder = embedder
        self._redis = redis
        self._settings = settings
        self._reranker = Reranker(llm)

    async def match_user(
        self, session: AsyncSession, user_id: uuid.UUID, now: datetime | None = None
    ) -> UserMatchSummary:
        now = now or datetime.now(UTC)
        summary = UserMatchSummary()
        resume_row = await store.get_current(session, user_id)
        if resume_row is None:
            summary.stopped = "no_resume"
            return summary
        prefs = await load_preferences(session, user_id)
        resume = MasterResume.model_validate(resume_row.data)
        candidates = await self._candidates(session, user_id, prefs, resume, resume_row.version, now)
        summary.candidates = len(candidates)
        if not candidates:
            return summary

        try:
            api_key = await resolve_api_key(session, user_id)
        except LLMKeyRequiredError:
            summary.stopped = "no_llm_key"
            return summary
        skills = user_skills(resume)
        candidate = candidate_payload(prefs, resume)
        used = await llm_calls_since(session, user_id, OPERATION, daily_window_start(now))
        allowance = self._settings.match_daily_llm_calls - used
        size = self._settings.match_batch_size

        with metered() as meter:
            for start in range(0, len(candidates), size):
                if meter.calls >= allowance:
                    summary.stopped = summary.stopped or "daily_allowance"
                    break
                batch = candidates[start : start + size]
                calls_before = meter.calls
                try:
                    outcome = await self._reranker.score_batch(
                        candidate,
                        [(job, company) for job, company, _ in batch],
                        api_key,
                        can_call=lambda: meter.calls < allowance,
                    )
                except (LLMQuotaExhaustedError, LLMRateLimitedError, LLMAuthError, LLMConfigError) as exc:
                    summary.stopped = type(exc).__name__
                    outcome = None
                await record_llm_usage(session, user_id, OPERATION, meter.calls - calls_before)
                if outcome is not None:
                    by_ref = {job_ref(job): (job, similarity) for job, _, similarity in batch}
                    for ref, result in outcome.scored.items():
                        job, similarity = by_ref[ref]
                        matched, missing = clean_skills(result, skills)
                        await _save_match(
                            session,
                            user_id,
                            job.id,
                            similarity,
                            llm_score=result.fit_score,
                            matched=matched,
                            missing=missing,
                            reasoning=result.reasoning,
                        )
                        if job.employment_type is None and result.employment_type in _CONCRETE_TYPES:
                            await _set_employment_type(session, job.id, result.employment_type)
                    for ref in outcome.unscorable:
                        job, similarity = by_ref[ref]
                        await _save_match(session, user_id, job.id, similarity, reasoning=UNSCORABLE_REASON)
                    summary.scored += len(outcome.scored)
                    summary.unscorable += len(outcome.unscorable)
                await session.commit()
                if outcome is None:
                    break
            summary.llm_calls = meter.calls
        return summary

    async def _candidates(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        prefs: PreferencesBase,
        resume: MasterResume,
        resume_version: int,
        now: datetime,
    ) -> list[tuple[Job, Company, float]]:
        """Unscored jobs passing the hard filters, ranked by similarity to the user's profile: the top
        `MATCH_CANDIDATES_PER_RUN` above `EMBED_MIN_SIM`."""
        conditions = hard_filter_conditions(
            user_id,
            max_job_age_days=prefs.max_job_age_days,
            employment_types=list(prefs.employment_types),
            company_stages=list(prefs.company_stages),
            now=now,
        )
        rows = (
            await session.execute(
                select(Job.id, Job.location, Job.remote).where(*conditions, ~_already_matched(user_id))
            )
        ).all()
        ids = filter_locations(list(rows), list(prefs.locations), prefs.remote_ok)
        if not ids:
            return []
        await embed_missing_jobs(session, self._embedder, now=now, job_ids=ids)

        vector = await user_embedding(
            self._redis,
            self._embedder,
            user_id,
            resume_version,
            profile_text(list(prefs.target_roles), resume),
        )
        distance = Job.embedding.cosine_distance(vector)
        result = await session.execute(
            select(Job, Company, (1 - distance).label("similarity"))
            .join(Company, Company.id == Job.company_id)
            .where(
                Job.id.in_(ids),
                Job.embedding.is_not(None),
                distance <= 1 - self._settings.embed_min_sim,
            )
            # Jobs whose stated type is one the user wants come before jobs of unknown type.
            .order_by(Job.employment_type.is_(None), distance, Job.id)
            .limit(self._settings.match_candidates_per_run)
        )
        return [(job, company, float(similarity)) for job, company, similarity in result.all()]

    async def match_all(self, sessions: async_sessionmaker[AsyncSession]) -> MatchRunSummary:
        """Every active user with a resume, one at a time (each uses their own key and allowance)."""
        run = MatchRunSummary()
        async with sessions() as session:
            user_ids: Sequence[uuid.UUID] = (
                await session.scalars(
                    select(User.id)
                    .where(User.is_active, exists().where(MasterResumeRow.user_id == User.id))
                    .order_by(User.created_at)
                )
            ).all()
        for user_id in user_ids:
            async with sessions() as session:
                try:
                    summary = await self.match_user(session, user_id)
                except Exception:
                    log.exception("matching failed for user %s", user_id)
                    run.stopped[str(user_id)] = "error"
                    continue
            run.users += 1
            run.scored += summary.scored
            run.llm_calls += summary.llm_calls
            if summary.stopped:
                run.stopped[str(user_id)] = summary.stopped
            log.info(
                "matched user %s: candidates=%d scored=%d unscorable=%d llm_calls=%d stopped=%s",
                user_id,
                summary.candidates,
                summary.scored,
                summary.unscorable,
                summary.llm_calls,
                summary.stopped,
            )
        return run


async def _save_match(
    session: AsyncSession,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    similarity: float,
    *,
    llm_score: int | None = None,
    matched: list[str] | None = None,
    missing: list[str] | None = None,
    reasoning: str,
) -> None:
    # DO NOTHING on conflict: a concurrent run already scored this pair (matching is incremental).
    await session.execute(
        insert(JobMatch)
        .values(
            user_id=user_id,
            job_id=job_id,
            embedding_score=similarity,
            llm_score=llm_score,
            matched_skills=matched or [],
            missing_skills=missing or [],
            reasoning=reasoning,
            status=JobMatchStatus.NEW,
        )
        .on_conflict_do_nothing(index_elements=[JobMatch.user_id, JobMatch.job_id])
    )


async def _set_employment_type(session: AsyncSession, job_id: uuid.UUID, employment_type: str) -> None:
    """Rules first, LLM fallback (PLAN.md Phase 2): fill a job's unknown type from the scoring answer."""
    await session.execute(
        update(Job)
        .where(Job.id == job_id, Job.employment_type.is_(None))
        .values(employment_type=employment_type)
    )


async def expire_matches(session: AsyncSession, now: datetime | None = None) -> int:
    """Matches whose job closed or got older than the user's max_job_age_days become `expired`
    (only from new/shortlisted; in-pipeline ones are left alone). Caller commits."""
    now = now or datetime.now(UTC)
    age_limit = (
        select(UserPreferences.max_job_age_days)
        .where(UserPreferences.user_id == JobMatch.user_id)
        .scalar_subquery()
    )
    too_old = (
        effective_date + func.make_interval(0, 0, 0, func.coalesce(age_limit, DEFAULT_MAX_AGE_DAYS)) < now
    )
    result = await session.execute(
        update(JobMatch)
        .where(
            JobMatch.job_id == Job.id,
            JobMatch.status.in_([JobMatchStatus.NEW, JobMatchStatus.SHORTLISTED]),
            or_(~Job.is_active, too_old),
        )
        .values(status=JobMatchStatus.EXPIRED)
        .returning(JobMatch.id)
    )
    return len(result.all())
