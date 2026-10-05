"""Company registry: the seed CSV (data/companies_seed.csv) plus companies created on the fly."""

import csv
import logging
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Company
from app.models.enums import AtsType, SizeHint
from app.services.sources.text import normalize_domain

log = logging.getLogger(__name__)


async def load_company_seed(session: AsyncSession, path: Path | None = None) -> int:
    """Upsert every row of the seed CSV, keyed by domain. Idempotent. Returns rows processed."""
    path = path or Path(get_settings().data_dir) / "companies_seed.csv"
    if not path.exists():
        log.warning("company seed %s not found", path)
        return 0
    with path.open(newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if (r.get("name") or "").strip()]
    for row in rows:
        values = {
            "name": row["name"].strip(),
            "domain": normalize_domain(row.get("domain")),
            "ats_type": AtsType((row.get("ats_type") or "none").strip()),
            "ats_token": (row.get("ats_token") or "").strip() or None,
            "size_hint": SizeHint((row.get("size_hint") or "unknown").strip()),
        }
        stmt = insert(Company).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Company.domain],
            set_={k: stmt.excluded[k] for k in ("name", "ats_type", "ats_token", "size_hint")},
        )
        await session.execute(stmt)
    await session.commit()
    return len(rows)


async def find_or_create_company(
    session: AsyncSession,
    *,
    name: str,
    domain: str | None = None,
    ats_type: AtsType = AtsType.NONE,
    ats_token: str | None = None,
) -> Company:
    """Match by ATS board, then domain, then case-insensitive name; otherwise create. Caller commits."""
    domain = normalize_domain(domain)
    if ats_token and ats_type != AtsType.NONE:
        found = await session.scalar(
            select(Company).where(Company.ats_type == ats_type, Company.ats_token == ats_token)
        )
        if found:
            return found
    if domain:
        found = await session.scalar(select(Company).where(Company.domain == domain))
        if found:
            return found
    found = await session.scalar(
        select(Company)
        .where(func.lower(Company.name) == name.strip().lower())
        .order_by(Company.created_at)
        .limit(1)
    )
    if found:
        if domain and not found.domain:
            found.domain = domain
        return found
    company = Company(
        name=name.strip()[:300],
        domain=domain,
        ats_type=ats_type if ats_token else AtsType.NONE,
        ats_token=ats_token,
    )
    session.add(company)
    await session.flush()
    return company
