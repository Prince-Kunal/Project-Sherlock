"""`discover_prospect_companies` (PLAN.md §8, Phase 8): for every active prospect target, find
matching companies with the company-search provider and upsert them; fetch website text for
candidates that have none (or a stale one); embed companies that changed.

Idempotent: companies are upserted by domain, website text is refreshed after 30 days at most, and
only companies without an embedding are embedded.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, ProspectTarget, User
from app.models.enums import SizeHint
from app.services.embeddings.embedder import Embedder
from app.services.prospects.base import CompanyIn, CompanySearchError, CompanySearchProvider
from app.services.prospects.filters import fits_target
from app.services.prospects.website import WebsiteFetcher

log = logging.getLogger(__name__)

MAX_PAGES = 3  # per target per run: up to 300 companies
WEBSITE_REFRESH_DAYS = 30
WEBSITES_PER_RUN = 40
WEBSITE_CONCURRENCY = 4  # different hosts in parallel; each host still gets ≤ 1 request/s
EMBED_WEBSITE_CHARS = 1500


@dataclass
class DiscoverySummary:
    targets: int = 0
    found: int = 0
    created: int = 0
    websites: int = 0
    embedded: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, int]:
        return {
            "targets": self.targets,
            "found": self.found,
            "created": self.created,
            "websites": self.websites,
            "embedded": self.embedded,
            "errors": len(self.errors),
        }


def company_text(company: Company) -> str:
    """Embedding text for a company: what it does, in its own words."""
    parts = [
        company.name,
        ", ".join(company.industry_tags[:12]),
        company.description or "",
        (company.website_text or "")[:EMBED_WEBSITE_CHARS],
    ]
    return "\n".join(p for p in parts if p).strip()


async def active_targets(session: AsyncSession, user_id: uuid.UUID | None = None) -> list[ProspectTarget]:
    query = (
        select(ProspectTarget)
        .join(User, User.id == ProspectTarget.user_id)
        .where(ProspectTarget.is_active.is_(True), User.is_active.is_(True))
        .order_by(ProspectTarget.created_at)
    )
    if user_id is not None:
        query = query.where(ProspectTarget.user_id == user_id)
    return list((await session.scalars(query)).all())


async def upsert_company(session: AsyncSession, found: CompanyIn) -> tuple[Company, bool]:
    """Insert, or fill in what the directory knows that the row doesn't. Returns (company, created).
    Names and sizes already known (seed list, Hunter) are kept; the directory's tags and places are
    taken as they are. A changed description clears the embedding so it's recomputed."""
    company = await session.scalar(select(Company).where(Company.domain == found.domain))
    created = company is None
    if company is None:
        company = Company(name=found.name[:300], domain=found.domain)
        session.add(company)
    if found.description and found.description != company.description:
        company.description = found.description
        company.embedding = None
    company.industry = company.industry or (found.industry or None)
    company.industry_tags = found.industry_tags or list(company.industry_tags or [])
    company.locations = found.locations or list(company.locations or [])
    company.hq_location = company.hq_location or found.hq_location
    if company.employee_count is None and found.employee_count is not None:
        company.employee_count = found.employee_count
    if company.size_hint in (None, SizeHint.UNKNOWN) and found.size_hint != SizeHint.UNKNOWN:
        company.size_hint = found.size_hint
    await session.flush()
    return company, created


def company_fits(company: Company, target: ProspectTarget) -> bool:
    return fits_target(
        tags=company.industry_tags or [],
        industry=company.industry,
        locations=[*(company.locations or []), *([company.hq_location] if company.hq_location else [])],
        size=company.size_hint,
        industries=list(target.industries),
        wanted_locations=list(target.locations),
        sizes=list(target.company_sizes),
    )


async def candidate_company_ids(session: AsyncSession, targets: list[ProspectTarget]) -> list[uuid.UUID]:
    """Companies (with a domain) that fit at least one target, each target's included companies
    first. Excluded companies of a target don't count for it."""
    included = [cid for t in targets for cid in t.include_companies]
    companies = (await session.scalars(select(Company).where(Company.domain.is_not(None)))).all()
    fitting = [
        c.id
        for c in companies
        if any(c.id not in t.exclude_companies and company_fits(c, t) for t in targets)
    ]
    ordered: list[uuid.UUID] = []
    for cid in [*included, *fitting]:
        if cid not in ordered:
            ordered.append(cid)
    return ordered


class Discovery:
    def __init__(self, provider: CompanySearchProvider, fetcher: WebsiteFetcher, embedder: Embedder) -> None:
        self._provider = provider
        self._fetcher = fetcher
        self._embedder = embedder

    async def run(
        self, session: AsyncSession, now: datetime, user_id: uuid.UUID | None = None
    ) -> DiscoverySummary:
        summary = DiscoverySummary()
        targets = await active_targets(session, user_id)
        summary.targets = len(targets)
        if not targets:
            return summary
        for target in targets:
            for page in range(1, MAX_PAGES + 1):
                try:
                    found = await self._provider.search_companies(
                        list(target.industries), list(target.locations), list(target.company_sizes), page
                    )
                except CompanySearchError as exc:
                    log.warning("company search failed for target %s: %s", target.id, exc)
                    summary.errors.append(str(exc))
                    break
                for item in found:
                    _, created = await upsert_company(session, item)
                    summary.found += 1
                    summary.created += int(created)
                await session.commit()
                if not found:
                    break
        summary.websites = await self.fetch_websites(session, targets, now)
        summary.embedded = await self.embed_companies(session)
        return summary

    async def fetch_websites(
        self,
        session: AsyncSession,
        targets: list[ProspectTarget],
        now: datetime,
        limit: int = WEBSITES_PER_RUN,
    ) -> int:
        """Website text for candidates that have none or a stale one; included companies and those
        without a description first."""
        ids = await candidate_company_ids(session, targets)
        if not ids:
            return 0
        stale = now - timedelta(days=WEBSITE_REFRESH_DAYS)
        rows = (
            await session.execute(
                select(Company.id, Company.domain, Company.description).where(
                    Company.id.in_(ids),
                    or_(Company.website_fetched_at.is_(None), Company.website_fetched_at < stale),
                )
            )
        ).all()
        rank = {cid: i for i, cid in enumerate(ids)}
        due = sorted(rows, key=lambda r: (r.description is not None, rank[r.id]))[:limit]
        if not due:
            return 0
        semaphore = asyncio.Semaphore(WEBSITE_CONCURRENCY)

        async def one(domain: str) -> str | None:
            async with semaphore:
                try:
                    return await self._fetcher.fetch(domain)
                except Exception:  # one bad site must not stop the run
                    log.exception("website fetch failed for %s", domain)
                    return None

        texts = await asyncio.gather(*(one(r.domain) for r in due))
        for row, text in zip(due, texts, strict=True):
            values: dict[str, object] = {"website_fetched_at": now}
            if text:
                values |= {"website_text": text, "embedding": None}
            await session.execute(update(Company).where(Company.id == row.id).values(**values))
        await session.commit()
        return sum(1 for t in texts if t)

    async def embed_companies(self, session: AsyncSession, batch_size: int = 64) -> int:
        ids = list(
            (
                await session.scalars(
                    select(Company.id)
                    .where(
                        Company.embedding.is_(None),
                        or_(Company.description.is_not(None), Company.website_text.is_not(None)),
                    )
                    .order_by(Company.id)
                )
            ).all()
        )
        for start in range(0, len(ids), batch_size):
            companies = (
                await session.scalars(
                    select(Company)
                    .where(Company.id.in_(ids[start : start + batch_size]))
                    .order_by(Company.id)
                )
            ).all()
            vectors = await self._embedder.embed([company_text(c) for c in companies])
            for company, vector in zip(companies, vectors, strict=True):
                company.embedding = vector
            await session.commit()
        if ids:
            log.info("embedded %d companies", len(ids))
        return len(ids)
