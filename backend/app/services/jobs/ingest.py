"""Upsert normalised jobs by dedupe_hash and track jobs that disappear from their source."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, literal_column, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, Job
from app.models.enums import JobSourceType
from app.services.sources.base import JobIn
from app.services.sources.text import dedupe_hash

MISSED_POLLS_BEFORE_INACTIVE = 3


@dataclass
class UpsertResult:
    created: int = 0
    updated: int = 0
    job_ids: list[uuid.UUID] | None = None


def job_hash(company: Company, job: JobIn) -> str:
    return dedupe_hash(company.domain, company.name, job.title, job.location)


async def upsert_jobs(
    session: AsyncSession, company: Company, jobs: list[JobIn], now: datetime
) -> UpsertResult:
    """Insert new jobs; refresh known ones (same dedupe_hash) and mark them seen. Caller commits."""
    rows: dict[str, dict[str, object]] = {}
    for job in jobs:
        key = job_hash(company, job)
        if key in rows:  # same company/title/location twice in one batch: keep the first
            continue
        rows[key] = {
            "company_id": company.id,
            "source": job.source,
            "external_id": job.external_id,
            "title": job.title,
            "location": job.location,
            "remote": job.remote,
            "employment_type": job.employment_type,
            "description_text": job.description_text,
            "url": job.url,
            "posted_at": job.posted_at,
            "first_seen_at": now,
            "last_seen_at": now,
            "missed_polls": 0,
            "is_active": True,
            "dedupe_hash": key,
            "source_meta": job.source_meta,
        }
    if not rows:
        return UpsertResult(job_ids=[])
    insert_stmt = insert(Job).values(list(rows.values()))
    excluded = insert_stmt.excluded
    # Typed loosely: SQLAlchemy's generic ReturningInsert[...] for a raw literal column is awkward to spell.
    stmt: Any = insert_stmt.on_conflict_do_update(
        index_elements=[Job.dedupe_hash],
        set_={
            "last_seen_at": excluded.last_seen_at,
            "missed_polls": 0,
            "is_active": True,
            "title": excluded.title,
            "location": excluded.location,
            "remote": func.coalesce(excluded.remote, Job.remote),
            "employment_type": func.coalesce(excluded.employment_type, Job.employment_type),
            "description_text": excluded.description_text,
            "url": func.coalesce(excluded.url, Job.url),
            # Keep the earliest known posting date.
            "posted_at": func.coalesce(func.least(Job.posted_at, excluded.posted_at), excluded.posted_at),
            "source_meta": func.coalesce(excluded.source_meta, Job.source_meta),
            "updated_at": func.now(),
        },
    ).returning(Job.id, literal_column("(xmax = 0)").label("inserted"))
    result = (await session.execute(stmt)).all()
    created = sum(1 for row in result if row.inserted)
    return UpsertResult(created=created, updated=len(result) - created, job_ids=[row.id for row in result])


async def mark_unseen(
    session: AsyncSession, company_id: uuid.UUID, source: JobSourceType, poll_started: datetime
) -> int:
    """After a successful board poll: jobs from that board not seen in it get a missed poll; after 3
    misses they become inactive. Returns how many were deactivated. Caller commits."""
    stmt = (
        update(Job)
        .where(
            Job.company_id == company_id,
            Job.source == source,
            Job.is_active,
            Job.last_seen_at < poll_started,
        )
        .values(
            missed_polls=Job.missed_polls + 1,
            is_active=Job.missed_polls + 1 < MISSED_POLLS_BEFORE_INACTIVE,
        )
        .returning(Job.is_active)
    )
    result = (await session.execute(stmt)).scalars().all()
    return sum(1 for active in result if not active)
