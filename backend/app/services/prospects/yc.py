"""The public YC company directory as a CompanySearchProvider (PLAN.md Phase 8, in place of Apollo's
organization search, which free accounts can't use).

yc-oss publishes every YC company as one JSON file (~10 MB, updated daily, no key): name, website,
one-liner and description, team size, industries and tags, offices and regions. It's fetched at most
once per `ttl` and filtered in memory. Only active, for-profit companies with a website are returned:
without a domain there's no one to email.
"""

import re
import time
from typing import Any

from app.services.prospects.base import CompanyIn, CompanySearchError, CompanySearchProvider
from app.services.prospects.filters import fits_target, size_from_count
from app.services.sources.http import PoliteHttpClient, SourceHTTPError
from app.services.sources.text import normalize_domain

YC_DIRECTORY_URL = "https://yc-oss.github.io/api/companies/all.json"
PAGE_SIZE = 100
DESCRIPTION_CHARS = 1500


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def parse_company(item: dict[str, Any]) -> CompanyIn | None:
    """One directory entry, or None when it can't be contacted (inactive, non-profit, no website)."""
    domain = normalize_domain(item.get("website"))
    if item.get("status") != "Active" or item.get("nonprofit") or not domain or not item.get("name"):
        return None
    offices = [p.strip() for p in (item.get("all_locations") or "").split(";") if p.strip()]
    regions = [r for r in item.get("regions") or [] if r and r != "Unspecified"]
    tags: list[str] = []
    raw_tags = [*(item.get("industries") or []), *(item.get("subindustry") or "").split("->")]
    for raw in [*raw_tags, *(item.get("tags") or [])]:
        tag = raw.strip().lower()
        if tag and tag not in tags:
            tags.append(tag)
    one_liner, long = _clean(item.get("one_liner")), _clean(item.get("long_description"))
    if one_liner and not one_liner.endswith((".", "!", "?")):
        one_liner += "."
    description = " ".join(p for p in (one_liner, long) if p)
    count = item.get("team_size") if isinstance(item.get("team_size"), int) else None
    return CompanyIn(
        name=str(item["name"]).strip(),
        domain=domain,
        description=description[:DESCRIPTION_CHARS] or None,
        industry=item.get("industry") or None,
        industry_tags=tags,
        locations=[*offices, *(r for r in regions if r not in offices)],
        hq_location=offices[0] if offices else None,
        employee_count=count,
        size_hint=size_from_count(count),
    )


class YCDirectory(CompanySearchProvider):
    name = "yc"

    def __init__(self, http: PoliteHttpClient, ttl_seconds: float = 12 * 3600) -> None:
        self._http = http
        self._ttl = ttl_seconds
        self._companies: list[CompanyIn] | None = None
        self._loaded_at = 0.0

    async def _all(self) -> list[CompanyIn]:
        if self._companies is None or time.monotonic() - self._loaded_at > self._ttl:
            try:
                data = await self._http.get_json(YC_DIRECTORY_URL)
            except SourceHTTPError as exc:
                raise CompanySearchError(f"YC directory: {exc}") from exc
            if not isinstance(data, list):
                raise CompanySearchError("YC directory: expected a list of companies")
            parsed = (parse_company(item) for item in data if isinstance(item, dict))
            self._companies = [c for c in parsed if c is not None]
            self._loaded_at = time.monotonic()
        return self._companies

    async def search_companies(
        self, industries: list[str], locations: list[str], sizes: list[str], page: int = 1
    ) -> list[CompanyIn]:
        matching = [
            c
            for c in await self._all()
            if fits_target(
                tags=c.industry_tags,
                industry=c.industry,
                locations=c.locations,
                size=c.size_hint,
                industries=industries,
                wanted_locations=locations,
                sizes=sizes,
            )
        ]
        start = (max(page, 1) - 1) * PAGE_SIZE
        return matching[start : start + PAGE_SIZE]
