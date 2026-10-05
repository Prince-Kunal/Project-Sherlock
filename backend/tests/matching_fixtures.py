"""Shared by the matching tests and tests/fixtures/record_llm.py (which must build the exact prompt the
tests replay). Must not import conftest: that would point settings at the test database."""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, Job, User, UserPreferences
from app.models.enums import JobSourceType
from app.schemas.preferences import PreferencesBase
from app.schemas.resume import MasterResume, ParsedResume
from app.services.jobs.companies import find_or_create_company
from app.services.jobs.ingest import job_hash, upsert_jobs
from app.services.llm.user_keys import save_key
from app.services.resume import store
from app.services.resume.parser import build_master_resume
from app.services.resume.skills import get_lexicon
from app.services.sources.base import JobIn

FIXTURES = Path(__file__).resolve().parent / "fixtures"
MATCH_JOBS = FIXTURES / "matching" / "jobs.json"

# The fixture user: wants Bangalore internships, remote OK.
FIXTURE_PREFS = PreferencesBase(
    target_roles=["Backend Engineer Intern", "Software Engineer Intern"],
    employment_types=["internship"],
    locations=["Bangalore"],
    remote_ok=True,
)
# Jobs that survive the hard filters for FIXTURE_PREFS, i.e. the ones sent to the LLM.
SCORED_KEYS = ["relevant", "irrelevant", "unknown_type"]


def fixture_resume() -> MasterResume:
    parsed = ParsedResume.model_validate_json(
        (FIXTURES / "llm" / "parse_resume" / "rohan_das.json").read_text()
    )
    return build_master_resume(
        parsed, email="rohan@example.com", phone=None, found_links=[], lexicon=get_lexicon()
    )


def fixture_jobs() -> list[dict[str, Any]]:
    return list(json.loads(MATCH_JOBS.read_text())["jobs"])


def job_in(item: dict[str, Any]) -> JobIn:
    return JobIn(
        source=JobSourceType.MANUAL,
        external_id=item["key"],
        company_name=item["company"]["name"],
        company_domain=item["company"]["domain"],
        title=item["title"],
        location=item["location"],
        remote=item["remote"],
        employment_type=item["employment_type"],
        description_text=item["description_text"],
        url=f"https://{item['company']['domain']}/jobs/{item['key']}",
    )


def unsaved_job(item: dict[str, Any]) -> tuple[Job, Company]:
    """In-memory Job + Company with the same dedupe hash the database rows get."""
    company = Company(name=item["company"]["name"], domain=item["company"]["domain"])
    data = job_in(item)
    job = Job(
        title=data.title,
        location=data.location,
        remote=data.remote,
        employment_type=data.employment_type,
        description_text=data.description_text,
        dedupe_hash=job_hash(company, data),
    )
    return job, company


PREF_COLUMNS = {
    "target_roles",
    "employment_types",
    "locations",
    "remote_ok",
    "min_fit_score",
    "max_job_age_days",
}


async def seed_matching_user(
    session: AsyncSession,
    *,
    user: User | None = None,
    email: str = "rohan@example.com",
    prefs: PreferencesBase = FIXTURE_PREFS,
    with_key: bool = True,
) -> User:
    """A user (new, or `user`) with the fixture resume, FIXTURE_PREFS and optionally a Gemini key."""
    if user is None:
        user = User(email=email, name="Rohan Das")
        session.add(user)
        await session.flush()
    existing = await session.scalar(select(UserPreferences).where(UserPreferences.user_id == user.id))
    values = prefs.model_dump(include=PREF_COLUMNS)
    if existing is None:
        session.add(UserPreferences(user_id=user.id, **values))
    else:
        for name, value in values.items():
            setattr(existing, name, value)
    await store.save_new_version(session, user.id, fixture_resume())
    if with_key:
        await save_key(session, user.id, "AIza-test-key-1234567890")
    await session.commit()
    return user


async def seed_fixture_jobs(
    session: AsyncSession, keys: list[str] | None = None, now: datetime | None = None
) -> dict[str, uuid.UUID]:
    """Insert the fixture jobs (all, or `keys`); returns job ids by fixture key."""
    now = now or datetime.now(UTC)
    ids: dict[str, uuid.UUID] = {}
    for item in fixture_jobs():
        if keys is not None and item["key"] not in keys:
            continue
        company = await find_or_create_company(
            session, name=item["company"]["name"], domain=item["company"]["domain"]
        )
        result = await upsert_jobs(session, company, [job_in(item)], now)
        ids[item["key"]] = (result.job_ids or [])[0]
    await session.commit()
    return ids
