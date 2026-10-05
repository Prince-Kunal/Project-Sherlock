"""Hard filters (PLAN.md Phase 3): cheap rules applied before embeddings or the LLM.

SQL conditions cover activity, age, blocked companies, employment type and company stage. Location is
a pure function applied in Python, because job locations are free text ("Remote - USA", "Bengaluru,
India", "San Francisco, CA | New York, NY") and the rules are easier to read and test here.
"""

import re
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, func, or_, select

from app.models import Company, Job, UserCompanyBlock
from app.models.enums import SizeHint
from app.services.sources.text import normalize_key

effective_date = func.coalesce(Job.posted_at, Job.first_seen_at)

# Titles that are never internships (PostgreSQL regex; \m and \M are word boundaries).
SENIOR_TITLE_PATTERN = (
    r"\m(senior|sr|staff|principal|lead|manager|director|head|vp|vice president|architect|chief"
    r"|cto|ceo|cfo|founding)\M|\m(ii|iii|iv)\M|\m(engineer|sde|developer)[ -]?[2-5]\M"
)


def hard_filter_conditions(
    user_id: uuid.UUID,
    *,
    max_job_age_days: int,
    employment_types: list[str],
    company_stages: list[str],
    now: datetime,
) -> list[ColumnElement[bool]]:
    """Jobs a user could be shown at all. Unknown values (no employment type, unknown company size)
    pass: the LLM decides the employment type during scoring."""
    blocked = select(UserCompanyBlock.company_id).where(UserCompanyBlock.user_id == user_id)
    conditions: list[ColumnElement[bool]] = [
        Job.is_active.is_(True),
        effective_date >= now - timedelta(days=max_job_age_days),
        Job.company_id.not_in(blocked),
    ]
    if employment_types:
        conditions.append(or_(Job.employment_type.in_(employment_types), Job.employment_type.is_(None)))
        if "full_time" not in employment_types:
            # Internship seekers: a job of unknown type titled "Senior …" or "SDE II" isn't one.
            conditions.append(
                or_(
                    Job.employment_type.is_not(None), ~Job.title.regexp_match(SENIOR_TITLE_PATTERN, flags="i")
                )
            )
    if company_stages:
        sized = select(Company.id).where(Company.size_hint.in_([*company_stages, SizeHint.UNKNOWN.value]))
        conditions.append(Job.company_id.in_(sized))
    return conditions


# A preferred place also matches these (normalize_key already maps bangalore→bengaluru etc.).
_INDIA_CITIES = [
    "bengaluru",
    "mumbai",
    "navi mumbai",
    "thane",
    "pune",
    "hyderabad",
    "chennai",
    "kolkata",
    "delhi",
    "gurugram",
    "noida",
    "ghaziabad",
    "faridabad",
    "ahmedabad",
    "jaipur",
    "kochi",
    "chandigarh",
    "indore",
    "coimbatore",
    "thiruvananthapuram",
    "mysuru",
]
_EXPANSIONS: dict[str, list[str]] = {
    "india": ["india", *_INDIA_CITIES],
    "ncr": ["delhi", "gurugram", "noida", "ghaziabad", "faridabad"],
    "delhi ncr": ["delhi", "gurugram", "noida", "ghaziabad", "faridabad"],
}
_REMOTE_WORDS = {"remote", "anywhere", "worldwide", "global", "distributed", "wfh"}
# Words that say nothing about where the job is.
_FILLER = {"fully", "work", "from", "home", "only", "first", "friendly", "or", "and", "in", "based", "100"}
_UNKNOWN_PLACE = {"hybrid", "multiple", "locations", "flexible", "various", "tbd", "office", "onsite"}
# Remote roles open to these regions also suit someone based in India.
_INDIA_REMOTE_REGIONS = {"india", "apac", "asia"}


def _words(key: str) -> set[str]:
    return set(key.split())


def _contains(key: str, place: str) -> bool:
    return re.search(rf"\b{re.escape(place)}\b", key) is not None


def location_matches(
    location: str | None, remote: bool | None, preferred: list[str], remote_ok: bool
) -> bool:
    """Whether a job's location suits the user's preferred locations.

    - No preferred locations: everything passes.
    - Unknown locations ("Hybrid", none given) pass; scoring sees them.
    - A preferred place (or a city it covers, e.g. "India" → Bengaluru) anywhere in the text passes.
    - Remote jobs pass when the user accepts remote work, unless they're tied to another region:
      "Remote" passes, "Remote - India" passes for someone in India, "Remote - USA" doesn't.
    """
    if not preferred:
        return True
    wanted_keys = [normalize_key(p) for p in preferred]
    wants_remote = remote_ok or any(k in _REMOTE_WORDS for k in wanted_keys)
    places = {place for k in wanted_keys if k and k not in _REMOTE_WORDS for place in _EXPANSIONS.get(k, [k])}

    key = normalize_key(location)
    words = _words(key)
    is_remote = bool(remote) or bool(words & _REMOTE_WORDS)
    if not (words - _FILLER - _UNKNOWN_PLACE - _REMOTE_WORDS):
        # No place named: either unknown ("Hybrid", empty) or plain "Remote".
        return wants_remote or not is_remote
    if any(_contains(key, place) for place in places):
        return True
    if wants_remote and is_remote:
        in_india = any(p in _INDIA_CITIES or p == "india" for p in places)
        return in_india and bool(words & _INDIA_REMOTE_REGIONS)
    return False


def filter_locations(rows: list[Any], preferred: list[str], remote_ok: bool) -> list[uuid.UUID]:
    """Ids of `(id, location, remote)` rows whose location suits the user."""
    return [row.id for row in rows if location_matches(row.location, row.remote, preferred, remote_ok)]
