"""ARQ worker entry point: `arq app.workers.settings.WorkerSettings`.

Every task must be idempotent and log a summary line (PLAN.md §8).
"""

import logging
from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings
from arq.cron import CronJob

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.logging import configure_logging
from app.core.redis import get_redis
from app.models.enums import AtsType
from app.services.jobs.poll import PollSources, hn_keywords, run_poll
from app.services.registry import get_llm_client
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
    return summary.as_dict()


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging()
    ctx["http"] = PoliteHttpClient()
    log.info("worker started")


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["http"].aclose()


class WorkerSettings:
    functions: ClassVar[list[Any]] = [poll_sources]
    cron_jobs: ClassVar[list[CronJob]] = [
        # Every 6h, off the top of the hour. Not at startup: restarts shouldn't hammer job boards.
        cron(poll_sources, hour={0, 6, 12, 18}, minute=7, timeout=3600, unique=True),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    job_timeout = 3600
