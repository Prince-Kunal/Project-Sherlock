"""ARQ worker entry point: `arq app.workers.settings.WorkerSettings`.

Every task must be idempotent and log a summary line (PLAN.md §8).
"""

import logging
from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings
from arq.cron import CronJob

from app.core.config import get_settings
from app.core.logging import configure_logging

log = logging.getLogger("app.workers")


async def noop(ctx: dict[str, Any]) -> dict[str, int]:
    """Phase 0 placeholder cron proving the scheduler runs. Replaced by real jobs from Phase 2."""
    summary = {"processed": 0, "succeeded": 0, "failed": 0}
    log.info("noop: processed=%(processed)d succeeded=%(succeeded)d failed=%(failed)d", summary)
    return summary


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging()
    log.info("worker started")


class WorkerSettings:
    functions: ClassVar[list[Any]] = [noop]
    cron_jobs: ClassVar[list[CronJob]] = [cron(noop, minute=set(range(0, 60, 5)), run_at_startup=True)]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
