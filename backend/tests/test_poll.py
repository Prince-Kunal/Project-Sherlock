"""Phase 2 acceptance: running poll_sources twice creates no duplicates; board jobs go inactive after
3 missed polls; a failed fetch is not a miss. All HTTP is mocked with recorded fixtures."""

import copy
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_sessionmaker
from app.models import Company, Job
from app.models.enums import AtsType, JobSourceType
from app.services.jobs.companies import load_company_seed
from app.services.jobs.poll import PollSources, run_poll
from app.services.sources.adzuna import AdzunaSource
from app.services.sources.ashby import AshbySource
from app.services.sources.greenhouse import GreenhouseSource
from app.services.sources.http import PoliteHttpClient
from app.services.sources.lever import LeverSource
from tests.conftest import FIXTURES

SOURCES = FIXTURES / "sources"
GH_URL = "https://boards-api.greenhouse.io/v1/boards/figma/jobs"
LEVER_URL = "https://api.lever.co/v0/postings/cred"
ASHBY_URL = "https://api.ashbyhq.com/posting-api/job-board/sarvam"
ADZUNA_URL = "https://api.adzuna.com/v1/api/jobs/in/search/1"


def load(path: str) -> Any:
    return json.loads((SOURCES / path).read_text())


@pytest.fixture
def seed(tmp_path: Path) -> Path:
    path = tmp_path / "companies_seed.csv"
    path.write_text(
        "name,domain,ats_type,ats_token,size_hint\n"
        "Figma,figma.com,greenhouse,figma,large\n"
        "CRED,cred.club,lever,cred,mid\n"
        "Sarvam AI,sarvam.ai,ashby,sarvam,startup\n"
    )
    return path


async def _no_sleep(_: float) -> None:
    return None


def _sources(adzuna: bool = False) -> PollSources:
    http = PoliteHttpClient(min_interval_seconds=0, sleep=_no_sleep)
    return PollSources(
        boards={
            AtsType.GREENHOUSE: GreenhouseSource(http),
            AtsType.LEVER: LeverSource(http),
            AtsType.ASHBY: AshbySource(http),
        },
        adzuna=AdzunaSource(http, "id", "key") if adzuna else None,
    )


def _mock_boards(greenhouse: dict[str, Any] | None = None) -> None:
    respx.get(GH_URL).mock(
        return_value=httpx.Response(200, json=greenhouse or load("greenhouse/board_figma.json"))
    )
    respx.get(LEVER_URL).mock(return_value=httpx.Response(200, json=load("lever/board_cred.json")))
    respx.get(ASHBY_URL).mock(return_value=httpx.Response(200, json=load("ashby/board_sarvam.json")))


async def _count_jobs(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(Job)) or 0


@respx.mock
async def test_polling_twice_creates_no_duplicates(seed: Path, session: AsyncSession) -> None:
    _mock_boards()
    respx.get(ADZUNA_URL).mock(return_value=httpx.Response(200, json=load("adzuna/search_in.json")))
    sessions = get_sessionmaker()

    # A user with a target role makes an Adzuna query.
    from app.models import User, UserPreferences

    user = User(email="u@example.com", name="U")
    session.add(user)
    await session.flush()
    session.add(UserPreferences(user_id=user.id, target_roles=["Backend Intern"]))
    await session.commit()

    first = await run_poll(sessions, _sources(adzuna=True), seed_path=seed)
    assert first.failed == 0, first.errors
    # Adzuna: 4 results, two of them the same JPMorganChase title + location → 3 jobs.
    assert first.jobs_created == 3 + 3 + 3 + 3
    assert await _count_jobs(session) == 12

    second = await run_poll(sessions, _sources(adzuna=True), seed_path=seed)
    assert second.jobs_created == 0
    assert second.jobs_updated == 12
    assert await _count_jobs(session) == 12
    assert (
        await session.scalar(select(func.count()).select_from(Company)) == 3 + 3
    )  # Adzuna companies by name

    # Board polls are recorded on the company.
    figma = await session.scalar(select(Company).where(Company.ats_token == "figma"))
    assert figma is not None
    assert figma.last_polled_at is not None


@respx.mock
async def test_job_inactive_after_three_missed_polls_and_revived_when_back(
    seed: Path, session: AsyncSession
) -> None:
    sessions = get_sessionmaker()
    board = load("greenhouse/board_figma.json")
    _mock_boards(board)
    await run_poll(sessions, _sources(), seed_path=seed)

    without_first = copy.deepcopy(board)
    gone_id = str(without_first["jobs"].pop(0)["id"])
    _mock_boards(without_first)

    async def gone_job() -> Job:
        session.expire_all()
        job = await session.scalar(select(Job).where(Job.external_id == gone_id))
        assert job is not None
        return job

    for expected_misses, expected_active in [(1, True), (2, True), (3, False)]:
        summary = await run_poll(sessions, _sources(), seed_path=seed)
        job = await gone_job()
        assert (job.missed_polls, job.is_active) == (expected_misses, expected_active)
    assert summary.jobs_deactivated == 1

    # Other boards' jobs were seen each time and stay active.
    active = await session.scalar(select(func.count()).select_from(Job).where(Job.is_active))
    assert active == 2 + 3 + 3

    # The posting comes back: active again, misses reset.
    _mock_boards(board)
    await run_poll(sessions, _sources(), seed_path=seed)
    job = await gone_job()
    assert (job.missed_polls, job.is_active) == (0, True)


@respx.mock
async def test_failed_fetch_is_not_a_missed_poll(seed: Path, session: AsyncSession) -> None:
    sessions = get_sessionmaker()
    _mock_boards()
    await run_poll(sessions, _sources(), seed_path=seed)

    respx.get(GH_URL).mock(return_value=httpx.Response(503))
    summary = await run_poll(sessions, _sources(), seed_path=seed)
    assert summary.failed == 1
    assert summary.succeeded == 2
    misses = await session.scalar(
        select(func.max(Job.missed_polls)).where(Job.source == JobSourceType.GREENHOUSE)
    )
    assert misses == 0


@respx.mock
async def test_malformed_postings_are_skipped_not_fatal(seed: Path, session: AsyncSession) -> None:
    board = load("greenhouse/board_figma.json")
    board["jobs"][0]["title"] = ""
    _mock_boards(board)
    summary = await run_poll(get_sessionmaker(), _sources(), seed_path=seed)
    assert summary.jobs_skipped == 1
    assert summary.jobs_created == 2 + 3 + 3


async def test_seed_load_is_idempotent(seed: Path, session: AsyncSession) -> None:
    assert await load_company_seed(session, seed) == 3
    assert await load_company_seed(session, seed) == 3
    assert await session.scalar(select(func.count()).select_from(Company)) == 3


async def test_real_seed_file_is_valid(session: AsyncSession) -> None:
    rows = await load_company_seed(session)
    assert 50 <= rows <= 100
    tokens = (await session.execute(select(Company.ats_type, Company.ats_token))).all()
    assert all(ats in {AtsType.GREENHOUSE, AtsType.LEVER, AtsType.ASHBY} and token for ats, token in tokens)
