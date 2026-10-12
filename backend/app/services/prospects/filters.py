"""Prospect-target filters (PLAN.md Phase 8): does a company fit a target's industries, locations and
sizes? Pure functions, shared by the company directory search and company matching.

Unknown values pass (a company of unknown size isn't excluded by a size filter), as with jobs.
"""

import re
from collections.abc import Iterable

from app.models.enums import SizeHint
from app.services.matching.filters import location_matches
from app.services.sources.text import normalize_key

STARTUP_MAX = 50
MID_MAX = 500

# A target industry also matches these tags.
_INDUSTRY_ALIASES: dict[str, list[str]] = {
    "ai": ["artificial intelligence", "machine learning", "generative ai", "ai"],
    "ml": ["machine learning", "artificial intelligence"],
    "machine learning": ["machine learning", "artificial intelligence", "ai"],
    "artificial intelligence": ["artificial intelligence", "machine learning", "ai"],
    "devtools": ["developer tools"],
    "dev tools": ["developer tools"],
    "edtech": ["education", "edtech"],
    "healthtech": ["healthcare", "health tech", "healthtech"],
    "saas": ["saas", "b2b"],
    "ecommerce": ["e-commerce", "ecommerce", "retail"],
    "security": ["security", "cybersecurity"],
    "data": ["data engineering", "analytics", "databases", "data"],
}


def size_from_count(count: int | None) -> SizeHint:
    if count is None or count <= 0:
        return SizeHint.UNKNOWN
    if count <= STARTUP_MAX:
        return SizeHint.STARTUP
    return SizeHint.MID if count <= MID_MAX else SizeHint.LARGE


def _key(value: str) -> str:
    return normalize_key(value.replace("&", " and "))


def industry_matches(tags: Iterable[str], industry: str | None, wanted: list[str]) -> bool:
    """Any wanted industry names one of the company's tags (whole words, either way round: "fintech"
    matches "fintech", "AI" matches "generative ai")."""
    if not wanted:
        return True
    have = {_key(t) for t in [*tags, industry or ""] if t}
    have.discard("")
    for want in (_key(w) for w in wanted):
        if not want:
            continue
        for term in _INDUSTRY_ALIASES.get(want, [want]):
            term = _key(term)
            if any(
                term == tag
                or re.search(rf"\b{re.escape(term)}\b", tag)
                or (len(tag) > 3 and re.search(rf"\b{re.escape(tag)}\b", term))
                for tag in have
            ):
                return True
    return False


def company_location_matches(locations: Iterable[str], wanted: list[str]) -> bool:
    """Any one of the company's places suits the target's locations. "Remote" in the target accepts
    companies listing a remote region; a remote region tied elsewhere doesn't count for "India"."""
    if not wanted:
        return True
    places = [p for p in locations if p and p.strip()]
    if not places:
        return True  # unknown location: let matching decide
    return any(location_matches(place, None, wanted, remote_ok=False) for place in places)


def size_matches(size: SizeHint, wanted: list[str]) -> bool:
    return not wanted or size == SizeHint.UNKNOWN or size.value in wanted


def fits_target(
    *,
    tags: Iterable[str],
    industry: str | None,
    locations: Iterable[str],
    size: SizeHint,
    industries: list[str],
    wanted_locations: list[str],
    sizes: list[str],
) -> bool:
    return (
        size_matches(size, sizes)
        and industry_matches(tags, industry, industries)
        and company_location_matches(locations, wanted_locations)
    )
