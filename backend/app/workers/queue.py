"""Enqueue worker tasks from the API."""

from typing import Any

from arq import create_pool
from arq.connections import RedisSettings

from app.core.config import get_settings


async def enqueue(function: str, *args: Any, job_id: str | None = None) -> str | None:
    """Queue `function` on the ARQ worker. Returns the job id, or None when a job with the same
    `job_id` is already queued or running (so repeated clicks don't stack up work)."""
    pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    try:
        job = await pool.enqueue_job(function, *args, _job_id=job_id)
    finally:
        await pool.aclose()
    return job.job_id if job else None
