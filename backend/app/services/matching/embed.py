"""Job and user-profile embeddings (PLAN.md Phase 3)."""

import hashlib
import json
import logging
import uuid
from collections.abc import Awaitable, Sequence
from datetime import datetime, timedelta
from typing import cast

from redis.asyncio import Redis
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Job, UserPreferences
from app.services.embeddings.embedder import Embedder
from app.services.matching.filters import effective_date
from app.services.matching.profile import job_text

log = logging.getLogger(__name__)

DEFAULT_MAX_AGE_DAYS = 14
_USER_VECTOR_TTL = 30 * 24 * 3600


async def embedding_age_window(session: AsyncSession) -> int:
    """Only jobs some user could still be shown are worth embedding: the largest max_job_age_days."""
    largest = await session.scalar(select(func.max(UserPreferences.max_job_age_days)))
    return max(largest or 0, DEFAULT_MAX_AGE_DAYS)


async def embed_missing_jobs(
    session: AsyncSession,
    embedder: Embedder,
    *,
    now: datetime,
    max_age_days: int | None = None,
    job_ids: Sequence[uuid.UUID] | None = None,
    batch_size: int = 64,
) -> int:
    """Embed active jobs that have no embedding yet (all within the age window, or just `job_ids`).
    Commits after each batch so a long first run makes progress. Returns how many were embedded."""
    conditions = [Job.is_active, Job.embedding.is_(None)]
    if job_ids is not None:
        conditions.append(Job.id.in_(job_ids))
    else:
        days = max_age_days or await embedding_age_window(session)
        conditions.append(effective_date >= now - timedelta(days=days))
    ids = list((await session.scalars(select(Job.id).where(*conditions).order_by(Job.id))).all())

    done = 0
    for start in range(0, len(ids), batch_size):
        chunk = ids[start : start + batch_size]
        jobs = (await session.scalars(select(Job).where(Job.id.in_(chunk)).order_by(Job.id))).all()
        vectors = await embedder.embed([job_text(job) for job in jobs])
        await session.execute(
            update(Job),
            [{"id": job.id, "embedding": vector} for job, vector in zip(jobs, vectors, strict=True)],
        )
        await session.commit()
        done += len(jobs)
    if done:
        log.info("embedded %d jobs", done)
    return done


async def user_embedding(
    redis: Redis, embedder: Embedder, user_id: uuid.UUID, resume_version: int, text: str
) -> list[float]:
    """Profile vector, cached per resume version (and per text, since target roles live in preferences)."""
    digest = hashlib.sha256(text.encode()).hexdigest()[:16]
    key = f"match:user_vec:{user_id}:{resume_version}:{digest}"
    cached = await cast(Awaitable[str | None], redis.get(key))
    if cached:
        return cast(list[float], json.loads(cached))
    [vector] = await embedder.embed([text])
    await cast(Awaitable[object], redis.set(key, json.dumps(vector), ex=_USER_VECTOR_TTL))
    return vector
