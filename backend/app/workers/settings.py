"""ARQ worker entry point: `arq app.workers.settings.WorkerSettings`.

Every task must be idempotent and log a summary line (PLAN.md §8).
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any, ClassVar

from arq import cron, func
from arq.connections import RedisSettings
from arq.cron import CronJob
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.logging import configure_logging, log_context
from app.core.redis import get_redis
from app.core.sentry import init_sentry
from app.models import Outreach, User
from app.models.enums import AtsType, OutreachStatus
from app.services.email.followups import Followups
from app.services.email.pipeline import DraftPipeline, users_due_for_drafts
from app.services.email.replies import WATCHED, ReplyChecker
from app.services.email.scheduler import Scheduler
from app.services.jobs.poll import PollSources, hn_keywords, run_poll
from app.services.matching.embed import embed_missing_jobs
from app.services.matching.pipeline import Matcher, expire_matches
from app.services.prospects.discovery import Discovery
from app.services.prospects.matching import CompanyMatcher
from app.services.prospects.website import WebsiteFetcher, website_http
from app.services.registry import (
    get_apollo_factory,
    get_company_search,
    get_contact_provider_factory,
    get_embedder,
    get_gmail_factory,
    get_llm_client,
)
from app.services.sources.adzuna import AdzunaSource
from app.services.sources.ashby import AshbySource
from app.services.sources.greenhouse import GreenhouseSource
from app.services.sources.hn import HNSource
from app.services.sources.http import PoliteHttpClient
from app.services.sources.lever import LeverSource

log = logging.getLogger("app.workers")

FOLLOWUP_HOUR = 8  # PLAN.md §8: create_followups at 08:00 (user time)


async def poll_sources(ctx: dict[str, Any]) -> dict[str, int]:
    settings = get_settings()
    http: PoliteHttpClient = ctx["http"]
    sessions = get_sessionmaker()
    hn = None
    if settings.hn_enabled and settings.gemini_api_key and not settings.use_fakes:
        async with sessions() as session:
            keywords = await hn_keywords(session)
        hn = HNSource(http, get_llm_client(), get_redis(), keywords=keywords)
    sources = PollSources(
        boards={
            AtsType.GREENHOUSE: GreenhouseSource(http),
            AtsType.LEVER: LeverSource(http),
            AtsType.ASHBY: AshbySource(http),
        },
        adzuna=AdzunaSource(http, settings.adzuna_app_id, settings.adzuna_app_key),
        hn=hn,
    )
    summary = await run_poll(sessions, sources)
    # PLAN.md §8: embed_new_jobs runs after poll_sources, match_jobs_for_users after embedding.
    await ctx["redis"].enqueue_job("embed_new_jobs", _job_id="embed_new_jobs:after_poll")
    return summary.as_dict()


async def embed_new_jobs(ctx: dict[str, Any]) -> dict[str, int]:
    async with get_sessionmaker()() as session:
        embedded = await embed_missing_jobs(session, get_embedder(), now=datetime.now(UTC))
    log.info("embed_new_jobs: embedded=%d", embedded)
    await ctx["redis"].enqueue_job("match_jobs_for_users", _job_id="match_jobs:after_poll")
    return {"embedded": embedded}


async def match_jobs_for_users(ctx: dict[str, Any], user_id: str | None = None) -> dict[str, int]:
    """Every active user with a resume, or just `user_id` (the "Refresh matches" button)."""
    settings = get_settings()
    matcher = Matcher(llm=get_llm_client(), embedder=get_embedder(), redis=get_redis(), settings=settings)
    sessions = get_sessionmaker()
    if user_id is None:
        run = await matcher.match_all(sessions)
        log.info("match_jobs_for_users: %s stopped=%s", run.as_dict(), run.stopped)
        return run.as_dict()
    async with sessions() as session:
        summary = await matcher.match_user(session, uuid.UUID(user_id))
    log.info("match_jobs_for_users: user=%s %s", user_id, summary)
    return {"users": 1, "scored": summary.scored, "llm_calls": summary.llm_calls}


async def expire_matches_task(ctx: dict[str, Any]) -> dict[str, int]:
    async with get_sessionmaker()() as session:
        expired = await expire_matches(session)
        await session.commit()
    log.info("expire_matches: expired=%d", expired)
    return {"expired": expired}


async def build_daily_drafts(ctx: dict[str, Any], user_id: str | None = None) -> dict[str, int]:
    """Hourly: users for whom it's 07:00 local time get today's batch (PLAN.md §8). With `user_id`
    (the "Build today's drafts" button) that user's batch runs now."""
    sessions = get_sessionmaker()
    if user_id is not None:
        user_ids = [uuid.UUID(user_id)]
    else:
        async with sessions() as session:
            user_ids = await users_due_for_drafts(session, get_redis(), datetime.now(UTC))
    if not user_ids:
        return {"users": 0, "drafted": 0, "failed": 0, "stopped": 0}
    pipeline = DraftPipeline(
        get_llm_client(),
        get_contact_provider_factory(),
        apollo_factory=get_apollo_factory(),
        fetcher=WebsiteFetcher(ctx["website_http"]),
    )
    run = await pipeline.build_all(sessions, user_ids)
    log.info("build_daily_drafts: %s stopped=%s", run.as_dict(), run.stopped)
    return run.as_dict()


async def first_run(ctx: dict[str, Any], user_id: str) -> dict[str, int]:
    """The end of onboarding (PLAN.md Phase 9): score jobs for a new user, then build today's drafts
    right away instead of waiting for the next poll and 07:00."""
    matched = await match_jobs_for_users(ctx, user_id)
    drafted = await build_daily_drafts(ctx, user_id)
    log.info("first_run: user=%s scored=%d drafted=%d", user_id, matched["scored"], drafted["drafted"])
    return {"scored": matched["scored"], "drafted": drafted["drafted"]}


async def discover_prospect_companies(ctx: dict[str, Any], user_id: str | None = None) -> dict[str, int]:
    """Daily (PLAN.md §8): companies for every active prospect target (or just `user_id`'s, from the
    "Find companies" button), their website text, and embeddings; then company matching."""
    discovery = Discovery(get_company_search(), WebsiteFetcher(ctx["website_http"]), get_embedder())
    async with get_sessionmaker()() as session:
        summary = await discovery.run(
            session, datetime.now(UTC), uuid.UUID(user_id) if user_id is not None else None
        )
    log.info("discover_prospect_companies: %s", summary.as_dict())
    if summary.targets:
        await ctx["redis"].enqueue_job(
            "match_companies_for_users", user_id, _job_id=f"match_companies:{user_id or 'all'}"
        )
    return summary.as_dict()


async def match_companies_for_users(ctx: dict[str, Any], user_id: str | None = None) -> dict[str, int]:
    """After discovery (PLAN.md §8): score new (user, company) pairs into company_matches."""
    settings = get_settings()
    matcher = CompanyMatcher(
        llm=get_llm_client(), embedder=get_embedder(), redis=get_redis(), settings=settings
    )
    sessions = get_sessionmaker()
    if user_id is None:
        run = await matcher.match_all(sessions)
        log.info("match_companies_for_users: %s stopped=%s", run.as_dict(), run.stopped)
        return run.as_dict()
    async with sessions() as session:
        summary = await matcher.match_user(session, uuid.UUID(user_id))
    log.info("match_companies_for_users: user=%s %s", user_id, summary)
    return {"users": 1, "scored": summary.scored, "llm_calls": summary.llm_calls}


async def _users_with(statuses: list[OutreachStatus], need_thread: bool = False) -> list[User]:
    async with get_sessionmaker()() as session:
        query = (
            select(User)
            .join(Outreach, Outreach.user_id == User.id)
            .where(User.is_active.is_(True), Outreach.status.in_(statuses))
            .distinct()
        )
        if need_thread:
            query = query.where(Outreach.gmail_thread_id.is_not(None))
        return list((await session.scalars(query)).all())


async def schedule_and_send(ctx: dict[str, Any]) -> dict[str, int]:
    """Every 5 min (PLAN.md §8): slot approved emails into each user's send window and send what's
    due, re-checking every send-time invariant (services/email/scheduler.py)."""
    totals = {"users": 0, "scheduled": 0, "sent": 0, "returned": 0, "waiting": 0}
    users = await _users_with([OutreachStatus.APPROVED, OutreachStatus.SCHEDULED])
    if not users:
        return totals
    scheduler = Scheduler(get_gmail_factory())
    for user in users:
        with log_context(user_id=user.id):
            async with get_sessionmaker()() as session:
                try:
                    summary = await scheduler.run_for_user(session, await session.merge(user))
                except Exception:  # one user's failure must not stop the others
                    log.exception("schedule_and_send failed for user %s", user.id)
                    continue
            totals["users"] += 1
            for key in ("scheduled", "sent", "returned", "waiting"):
                totals[key] += getattr(summary, key)
    log.info("schedule_and_send: %s", totals)
    return totals


async def check_replies(ctx: dict[str, Any]) -> dict[str, int]:
    """Every 30 min: replies, bounces and opt-outs in sent threads (services/email/replies.py)."""
    totals = {"users": 0, "checked": 0, "replied": 0, "opted_out": 0, "bounced": 0, "errors": 0}
    users = await _users_with(list(WATCHED), need_thread=True)
    if not users:
        return totals
    checker = ReplyChecker(get_gmail_factory(), get_llm_client())
    for user in users:
        with log_context(user_id=user.id):
            async with get_sessionmaker()() as session:
                try:
                    summary = await checker.run_for_user(session, await session.merge(user))
                except Exception:
                    log.exception("check_replies failed for user %s", user.id)
                    continue
            totals["users"] += 1
            for key in ("checked", "replied", "opted_out", "bounced", "errors"):
                totals[key] += getattr(summary, key)
    log.info("check_replies: %s", totals)
    return totals


async def create_followups(ctx: dict[str, Any], user_id: str | None = None) -> dict[str, int]:
    """Hourly; each user's run happens at 08:00 their time (PLAN.md §8 "daily 08:00")."""
    sessions = get_sessionmaker()
    if user_id is not None:
        user_ids = [uuid.UUID(user_id)]
    else:
        async with sessions() as session:
            user_ids = await users_due_for_drafts(
                session, get_redis(), datetime.now(UTC), hour=FOLLOWUP_HOUR, job="followups_built"
            )
    totals = {"users": 0, "drafted": 0, "failed": 0, "upgraded": 0}
    followups = Followups(get_llm_client())
    for uid in user_ids:
        with log_context(user_id=uid):
            async with sessions() as session:
                try:
                    summary = await followups.run_for_user(session, uid)
                except Exception:
                    log.exception("create_followups failed for user %s", uid)
                    continue
            totals["users"] += 1
            totals["drafted"] += summary.drafted
            totals["failed"] += summary.failed
            totals["upgraded"] += summary.upgraded
    log.info("create_followups: %s", totals)
    return totals


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging()
    init_sentry("worker")
    ctx["http"] = PoliteHttpClient()
    ctx["website_http"] = website_http()
    log.info("worker started")


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["http"].aclose()
    await ctx["website_http"].aclose()


class WorkerSettings:
    functions: ClassVar[list[Any]] = [
        poll_sources,
        embed_new_jobs,
        # Results kept briefly: the job id doubles as a "already queued" guard for "Refresh matches",
        # and a long-kept result would block the next refresh.
        func(match_jobs_for_users, keep_result=60),
        func(build_daily_drafts, keep_result=60),
        schedule_and_send,
        check_replies,
        create_followups,
        func(discover_prospect_companies, keep_result=60, timeout=3600),
        func(match_companies_for_users, keep_result=60),
        func(first_run, keep_result=60, timeout=3600),
    ]
    cron_jobs: ClassVar[list[CronJob]] = [
        # Every 6h, off the top of the hour. Not at startup: restarts shouldn't hammer job boards.
        cron(poll_sources, hour={0, 6, 12, 18}, minute=7, timeout=3600, unique=True),
        cron(expire_matches_task, name="expire_matches", hour={1}, minute=15, unique=True),
        # Hourly; each user's batch runs in the hour that is 07:00 in their timezone.
        cron(build_daily_drafts, minute={2}, timeout=3600, unique=True),
        cron(schedule_and_send, minute=set(range(0, 60, 5)), timeout=600, unique=True),
        cron(check_replies, minute={11, 41}, timeout=900, unique=True),
        cron(create_followups, minute={4}, timeout=1800, unique=True),
        # Daily, before the morning drafts in India (23:37 UTC is 05:07 IST); matching follows it.
        cron(discover_prospect_companies, hour={23}, minute=37, timeout=3600, unique=True),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    job_timeout = 3600
