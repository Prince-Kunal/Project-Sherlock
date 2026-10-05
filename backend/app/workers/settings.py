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

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.logging import configure_logging
from app.core.redis import get_redis
from app.models.enums import AtsType
from app.services.jobs.poll import PollSources, hn_keywords, run_poll
from app.services.matching.embed import embed_missing_jobs
from app.services.matching.pipeline import Matcher, expire_matches
from app.services.registry import get_embedder, get_llm_client
from app.services.sources.adzuna import AdzunaSource
from app.services.sources.ashby import AshbySource
from app.services.sources.greenhouse import GreenhouseSource
from app.services.sources.hn import HNSource
from app.services.sources.http import PoliteHttpClient
from app.services.sources.lever import LeverSource

log = logging.getLogger("app.workers")


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


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging()
    ctx["http"] = PoliteHttpClient()
    log.info("worker started")


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["http"].aclose()


class WorkerSettings:
    functions: ClassVar[list[Any]] = [
        poll_sources,
        embed_new_jobs,
        # Results kept briefly: the job id doubles as a "already queued" guard for "Refresh matches",
        # and a long-kept result would block the next refresh.
        func(match_jobs_for_users, keep_result=60),
    ]
    cron_jobs: ClassVar[list[CronJob]] = [
        # Every 6h, off the top of the hour. Not at startup: restarts shouldn't hammer job boards.
        cron(poll_sources, hour={0, 6, 12, 18}, minute=7, timeout=3600, unique=True),
        cron(expire_matches_task, name="expire_matches", hour={1}, minute=15, unique=True),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    job_timeout = 3600
