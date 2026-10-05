"""poll_sources (PLAN.md §8): poll every company's ATS board plus aggregator queries, upsert jobs, and
mark board jobs inactive after 3 missed polls. Idempotent: running it twice creates no duplicates."""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Company, User, UserPreferences
from app.models.enums import AtsType
from app.services.jobs.companies import find_or_create_company, load_company_seed
from app.services.jobs.ingest import mark_unseen, upsert_jobs
from app.services.sources.adzuna import AdzunaSource
from app.services.sources.base import CompanyRef, JobIn, JobQuery, JobSource, MalformedJobError, RawJob
from app.services.sources.hn import DEFAULT_KEYWORDS, HNSource
from app.services.sources.http import SourceHTTPError

log = logging.getLogger(__name__)

MAX_ADZUNA_QUERIES = 10


@dataclass
class PollSummary:
    processed: int = 0  # boards + queries attempted
    succeeded: int = 0
    failed: int = 0
    jobs_created: int = 0
    jobs_updated: int = 0
    jobs_deactivated: int = 0
    jobs_skipped: int = 0  # malformed postings
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, int]:
        return {k: v for k, v in self.__dict__.items() if isinstance(v, int)}


@dataclass
class PollSources:
    boards: dict[AtsType, JobSource]
    adzuna: AdzunaSource | None = None
    hn: HNSource | None = None


def _normalize_all(source: JobSource, raws: list[RawJob], summary: PollSummary) -> list[JobIn]:
    jobs = []
    for raw in raws:
        try:
            jobs.append(source.normalize(raw))
        except (MalformedJobError, ValueError) as exc:
            summary.jobs_skipped += 1
            log.debug("skipping %s job %s: %s", source.source.value, raw.external_id, exc)
    return jobs


async def _poll_board(
    sessions: async_sessionmaker[AsyncSession], source: JobSource, company_id: object, summary: PollSummary
) -> None:
    async with sessions() as session:
        company = await session.get(Company, company_id)
        if company is None or not company.ats_token:
            return
        ref = CompanyRef(
            id=company.id,
            name=company.name,
            domain=company.domain,
            ats_type=company.ats_type,
            ats_token=company.ats_token,
        )
        summary.processed += 1
        started = datetime.now(UTC)
        try:
            raws = await source.fetch(ref)
        except SourceHTTPError as exc:
            # A failed fetch must not count as a "missed poll" for the board's jobs.
            summary.failed += 1
            summary.errors.append(f"{company.name}: {exc}")
            log.warning("poll %s (%s) failed: %s", company.name, source.source.value, exc)
            return
        jobs = _normalize_all(source, raws, summary)
        result = await upsert_jobs(session, company, jobs, started)
        deactivated = await mark_unseen(session, company.id, source.source, started)
        company.last_polled_at = started
        await session.commit()
        summary.succeeded += 1
        summary.jobs_created += result.created
        summary.jobs_updated += result.updated
        summary.jobs_deactivated += deactivated


async def _ingest_aggregated(
    sessions: async_sessionmaker[AsyncSession], source: JobSource, raws: list[RawJob], summary: PollSummary
) -> None:
    """Aggregator jobs (Adzuna, HN) come from many companies; create companies on the fly by name.
    No missed-poll tracking: a job missing from a search result isn't necessarily closed (it ages out)."""
    jobs = _normalize_all(source, raws, summary)
    now = datetime.now(UTC)
    async with sessions() as session:
        by_company: dict[tuple[str, str | None], list[JobIn]] = {}
        for job in jobs:
            by_company.setdefault((job.company_name.strip().lower(), job.company_domain), []).append(job)
        for group in by_company.values():
            company = await find_or_create_company(
                session, name=group[0].company_name, domain=group[0].company_domain
            )
            result = await upsert_jobs(session, company, group, now)
            summary.jobs_created += result.created
            summary.jobs_updated += result.updated
        await session.commit()


async def adzuna_queries(session: AsyncSession) -> list[JobQuery]:
    """One query per distinct target role across active, non-paused users."""
    rows = await session.execute(
        select(UserPreferences.target_roles)
        .join(User, User.id == UserPreferences.user_id)
        .where(User.is_active, UserPreferences.paused.is_(False))
    )
    roles = sorted({r.strip().lower() for (target_roles,) in rows for r in target_roles if r.strip()})
    return [JobQuery(what=role) for role in roles[:MAX_ADZUNA_QUERIES]]


async def hn_keywords(session: AsyncSession) -> list[str]:
    rows = await session.execute(
        select(UserPreferences.locations).join(User, User.id == UserPreferences.user_id).where(User.is_active)
    )
    locations = {loc.strip().lower() for (locs,) in rows for loc in locs if loc.strip()}
    return sorted(set(DEFAULT_KEYWORDS) | locations)


async def run_poll(
    sessions: async_sessionmaker[AsyncSession],
    sources: PollSources,
    *,
    concurrency: int = 6,
    seed_path: Path | None = None,
) -> PollSummary:
    summary = PollSummary()
    async with sessions() as session:
        await load_company_seed(session, seed_path)
        boards = (
            await session.execute(
                select(Company.id, Company.ats_type).where(
                    Company.ats_type != AtsType.NONE, Company.ats_token.is_not(None)
                )
            )
        ).all()
        queries = await adzuna_queries(session) if sources.adzuna and sources.adzuna.configured else []

    semaphore = asyncio.Semaphore(concurrency)

    async def board_task(company_id: object, ats_type: AtsType) -> None:
        source = sources.boards.get(ats_type)
        if source is None:
            return
        async with semaphore:
            try:
                await _poll_board(sessions, source, company_id, summary)
            except Exception as exc:  # one bad board must not stop the rest
                summary.failed += 1
                summary.errors.append(f"{company_id}: {type(exc).__name__}")
                log.exception("poll of company %s crashed", company_id)

    await asyncio.gather(*(board_task(cid, ats) for cid, ats in boards))

    if sources.adzuna and sources.adzuna.configured:
        for query in queries:
            summary.processed += 1
            try:
                raws = await sources.adzuna.fetch(query)
                await _ingest_aggregated(sessions, sources.adzuna, raws, summary)
                summary.succeeded += 1
            except SourceHTTPError as exc:
                summary.failed += 1
                summary.errors.append(f"adzuna {query.what!r}: {exc}")
    elif sources.adzuna is not None:
        log.info("poll: Adzuna skipped (ADZUNA_APP_ID / ADZUNA_APP_KEY not set)")

    if sources.hn is not None:
        summary.processed += 1
        try:
            raws = await sources.hn.fetch(None)
            await _ingest_aggregated(sessions, sources.hn, raws, summary)
            summary.succeeded += 1
        except SourceHTTPError as exc:
            summary.failed += 1
            summary.errors.append(f"hn: {exc}")

    log.info(
        "poll_sources: processed=%d succeeded=%d failed=%d created=%d updated=%d deactivated=%d skipped=%d",
        summary.processed,
        summary.succeeded,
        summary.failed,
        summary.jobs_created,
        summary.jobs_updated,
        summary.jobs_deactivated,
        summary.jobs_skipped,
    )
    return summary
