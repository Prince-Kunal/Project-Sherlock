"""Phase 10 sources: SmartRecruiters, Workable and Recruitee boards and Remotive, coded against real
recorded responses (tests/fixtures/record_sources.py more), and each user's choice of feeds."""

import copy
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_sessionmaker
from app.models import Company, Job, User, UserPreferences
from app.models.enums import AtsType, JobSourceType, sources_for
from app.services.jobs.ingest import upsert_jobs
from app.services.jobs.poll import PollSources, adzuna_queries, run_poll, wanted_feeds
from app.services.matching.filters import hard_filter_conditions, location_matches
from app.services.sources.base import CompanyRef, JobIn, RawJob
from app.services.sources.http import PoliteHttpClient
from app.services.sources.recruitee import RecruiteeSource
from app.services.sources.remotive import API_URL as REMOTIVE_URL
from app.services.sources.remotive import RemotiveSource
from app.services.sources.smartrecruiters import SmartRecruitersSource
from app.services.sources.workable import WorkableSource
from tests.conftest import FIXTURES

SOURCES = FIXTURES / "sources"
SR_BOARD = "https://api.smartrecruiters.com/v1/companies/Freshworks/postings"


def load(path: str) -> Any:
    return json.loads((SOURCES / path).read_text())


async def _no_sleep(_: float) -> None:
    return None


@pytest.fixture
def http() -> PoliteHttpClient:
    return PoliteHttpClient(min_interval_seconds=0, sleep=_no_sleep)


def ref(ats: AtsType, token: str, name: str, known: frozenset[str] = frozenset()) -> CompanyRef:
    return CompanyRef(id=uuid.uuid4(), name=name, domain=None, ats_type=ats, ats_token=token, known_ids=known)


# --- SmartRecruiters ----------------------------------------------------------------------------------


def _sr_detail(posting_id: str) -> dict[str, Any]:
    detail = copy.deepcopy(load("smartrecruiters/job_freshworks.json"))
    detail["id"] = posting_id
    return detail


@respx.mock
async def test_smartrecruiters_fetches_details_only_for_new_recent_postings(http: PoliteHttpClient) -> None:
    board = load("smartrecruiters/board_freshworks.json")
    ids = [p["id"] for p in board["content"]]
    respx.get(SR_BOARD).mock(return_value=httpx.Response(200, json=board))
    details = respx.get(url__regex=rf"{SR_BOARD}/\d+$").mock(
        side_effect=lambda request: httpx.Response(200, json=_sr_detail(request.url.path.rsplit("/", 1)[1]))
    )
    source = SmartRecruitersSource(http, max_details=1, now=datetime(2026, 10, 13, tzinfo=UTC))
    raws = await source.fetch(ref(AtsType.SMARTRECRUITERS, "Freshworks", "Freshworks", frozenset({ids[2]})))

    assert [r.external_id for r in raws] == ids
    assert details.call_count == 1  # one new posting allowed; the known one is never re-fetched
    jobs = [source.normalize(r) for r in raws]
    first = jobs[0]
    assert first.source == JobSourceType.SMARTRECRUITERS
    assert (first.title, first.location, first.remote) == (
        "Lead Software Engineer - Systems",
        "Chennai, India",
        None,
    )
    assert first.employment_type == "full_time"
    assert (
        first.url
        == "https://jobs.smartrecruiters.com/Freshworks/744000154405299-lead-software-engineer-systems"
    )
    assert first.posted_at == datetime(2026, 10, 8, 10, 53, 4, 656000, tzinfo=UTC)
    assert "Freshworks" in first.description_text
    assert "<p>" not in first.description_text
    assert jobs[1].description_text == ""  # over the detail budget: kept for the next poll
    assert jobs[1].url == f"https://jobs.smartrecruiters.com/Freshworks/{ids[1]}"


@respx.mock
async def test_smartrecruiters_skips_postings_older_than_the_window(http: PoliteHttpClient) -> None:
    respx.get(SR_BOARD).mock(
        return_value=httpx.Response(200, json=load("smartrecruiters/board_freshworks.json"))
    )
    source = SmartRecruitersSource(http, now=datetime(2026, 12, 1, tzinfo=UTC))
    assert await source.fetch(ref(AtsType.SMARTRECRUITERS, "Freshworks", "Freshworks")) == []


# --- Workable ---------------------------------------------------------------------------------------


@respx.mock
async def test_workable_fetch_and_normalize(http: PoliteHttpClient) -> None:
    route = respx.get("https://apply.workable.com/api/v1/widget/accounts/huggingface").mock(
        return_value=httpx.Response(200, json=load("workable/board_huggingface.json"))
    )
    source = WorkableSource(http)
    jobs = [
        source.normalize(r) for r in await source.fetch(ref(AtsType.WORKABLE, "huggingface", "Hugging Face"))
    ]
    assert route.calls.last.request.url.params["details"] == "true"
    assert len(jobs) == 3
    job = jobs[0]
    assert job.external_id == "81B46579FE"
    assert (job.location, job.remote, job.employment_type) == ("Remote - Paris, France", True, "full_time")
    assert job.url == "https://apply.workable.com/j/81B46579FE"
    assert job.posted_at == datetime(2026, 5, 29, tzinfo=UTC)
    assert "Hugging Face" in job.description_text


# --- Recruitee --------------------------------------------------------------------------------------


@respx.mock
async def test_recruitee_fetch_and_normalize(http: PoliteHttpClient) -> None:
    respx.get("https://bunq.recruitee.com/api/offers/").mock(
        return_value=httpx.Response(200, json=load("recruitee/board_bunq.json"))
    )
    source = RecruiteeSource(http)
    jobs = [source.normalize(r) for r in await source.fetch(ref(AtsType.RECRUITEE, "bunq", "bunq"))]
    assert [j.external_id for j in jobs] == ["2780064", "2774877", "2771751"]
    lead, intern, _ = jobs
    assert lead.location == "Amsterdam, Netherlands; İstanbul, Türkiye; Sofia, Bulgaria"
    assert (lead.employment_type, lead.remote) == ("full_time", None)
    assert intern.employment_type == "internship"  # the title wins over "fulltime_permanent"
    assert lead.url == "https://careers.bunq.com/o/transaction-review-lead-5"
    assert lead.posted_at == datetime(2026, 10, 12, 13, 59, 52, tzinfo=UTC)
    assert "bunq" in lead.description_text


def test_recruitee_remote_offer_without_locations() -> None:
    offer = copy.deepcopy(load("recruitee/board_bunq.json")["offers"][0])
    offer["remote"] = True
    offer["locations"] = []
    raw = RawJob(source=JobSourceType.RECRUITEE, external_id="1", payload=offer, company_name="bunq")
    job = RecruiteeSource(http=None).normalize(raw)  # type: ignore[arg-type]
    assert job.location == "Remote - Amsterdam, Noord-Holland, Netherlands"
    assert job.remote is True


# --- Remotive ---------------------------------------------------------------------------------------


@respx.mock
async def test_remotive_dedupes_across_categories_and_credits_remotive(http: PoliteHttpClient) -> None:
    route = respx.get(REMOTIVE_URL).mock(return_value=httpx.Response(200, json=load("remotive/jobs.json")))
    source = RemotiveSource(http, categories=("software-dev", "data"))
    raws = await source.fetch(None)
    assert route.call_count == 2
    assert [r.external_id for r in raws] == ["2086540", "2091045", "2091149"]
    jobs = [source.normalize(r) for r in raws]
    job = jobs[2]
    assert job.company_name == "CodeForAI"
    assert job.location.startswith("Remote - USA, UK, India")  # type: ignore[union-attr]
    assert (job.remote, job.employment_type) == (True, "contract")
    assert job.url == (
        "https://remotive.com/remote-jobs/software-development/"
        "software-engineer-ai-code-trainer-python-web-full-stack-2091149"
    )
    assert job.source_meta == {"attribution": "Remotive", "category": "Software Development"}
    assert job.posted_at == datetime(2026, 10, 5, 5, 15, 43, tzinfo=UTC)
    assert job.company_domain is None


def test_remote_regions_follow_the_location_rules() -> None:
    """A worldwide remote job fits an India-based user; a US-only one doesn't."""
    assert location_matches("Remote - Worldwide", True, ["India"], True)
    assert location_matches("Remote - USA, UK, India, Australia", True, ["India"], True)
    assert not location_matches("Remote - USA", True, ["India"], True)


# --- Each user's choice of feeds ----------------------------------------------------------------------


def test_feeds_map_to_sources() -> None:
    assert sources_for([]) == [JobSourceType.MANUAL]
    boards = set(sources_for(["boards"]))
    assert {JobSourceType.SMARTRECRUITERS, JobSourceType.WORKABLE, JobSourceType.RECRUITEE} <= boards
    assert JobSourceType.REMOTIVE not in boards
    assert JobSourceType.REMOTIVE in sources_for(["remotive"])


async def _user(session: AsyncSession, email: str, feeds: list[str], roles: list[str]) -> User:
    user = User(email=email, name=email)
    session.add(user)
    await session.flush()
    session.add(UserPreferences(user_id=user.id, job_sources=feeds, target_roles=roles))
    await session.commit()
    return user


async def test_aggregators_are_only_asked_for_when_someone_wants_them(
    session: AsyncSession, http: PoliteHttpClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _user(session, "boards@x.example", ["boards"], ["Backend Intern"])
    await _user(session, "adzuna@x.example", ["boards", "adzuna"], ["Data Analyst"])
    assert await wanted_feeds(session) == {"boards", "adzuna"}
    assert [q.what for q in await adzuna_queries(session)] == ["data analyst"]

    calls: list[str] = []

    class Spy(RemotiveSource):
        async def fetch(self, target: object = None) -> list[Any]:
            calls.append("remotive")
            return []

    monkeypatch.setattr("app.services.jobs.poll.load_company_seed", _no_seed)
    await run_poll(get_sessionmaker(), PollSources(boards={}, remotive=Spy(http)))
    assert calls == []
    await _user(session, "remote@x.example", ["remotive"], [])
    await run_poll(get_sessionmaker(), PollSources(boards={}, remotive=Spy(http)))
    assert calls == ["remotive"]


async def _no_seed(*_: object, **__: object) -> None:
    return None


async def test_matches_only_come_from_the_users_feeds(session: AsyncSession) -> None:
    company = Company(name="Feeds Co")
    session.add(company)
    await session.flush()
    now = datetime.now(UTC)
    for source in (JobSourceType.REMOTIVE, JobSourceType.WORKABLE, JobSourceType.MANUAL, JobSourceType.HN):
        session.add(
            Job(
                company_id=company.id,
                source=source,
                title=f"{source.value} job",
                dedupe_hash=uuid.uuid4().hex,
                posted_at=now - timedelta(days=1),
            )
        )
    await session.commit()

    async def visible(feeds: list[str] | None) -> set[str]:
        conditions = hard_filter_conditions(
            uuid.uuid4(),
            max_job_age_days=14,
            employment_types=[],
            company_stages=[],
            now=now,
            job_sources=feeds,
        )
        return {j.source.value for j in (await session.scalars(select(Job).where(*conditions))).all()}

    assert await visible(["boards"]) == {"workable", "manual"}
    assert await visible(["remotive", "hn"]) == {"remotive", "hn", "manual"}
    assert await visible(None) == {"remotive", "workable", "manual", "hn"}


async def test_a_repoll_without_a_description_keeps_the_stored_one(session: AsyncSession) -> None:
    company = Company(name="Keep Co", domain="keep.example")
    session.add(company)
    await session.flush()
    job = JobIn(
        source=JobSourceType.SMARTRECRUITERS, external_id="1", company_name="Keep Co", title="Backend Intern",
        description_text="Build APIs in Python.",
    )  # fmt: skip
    now = datetime.now(UTC)
    await upsert_jobs(session, company, [job], now)
    await upsert_jobs(session, company, [job.model_copy(update={"description_text": ""})], now)
    await upsert_jobs(session, company, [job.model_copy(update={"description_text": "New text."})], now)
    await session.commit()
    texts = (await session.scalars(select(Job.description_text).where(Job.company_id == company.id))).all()
    assert texts == ["New text."]


@respx.mock
async def test_admin_can_register_the_new_board_types(auth_client: Any) -> None:
    respx.get("https://apply.workable.com/api/v1/widget/accounts/huggingface").mock(
        return_value=httpx.Response(200, json=load("workable/board_huggingface.json"))
    )
    response = await auth_client.post(
        "/admin/companies",
        json={
            "name": "Hugging Face",
            "domain": "huggingface.co",
            "ats_type": "workable",
            "ats_token": "huggingface",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["jobs_on_board"] == 3


# --- Job links pasted (or sent from the browser extension) -----------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://jobs.smartrecruiters.com/Freshworks/744000154405299-lead-software-engineer-systems",
            (AtsType.SMARTRECRUITERS, "Freshworks", "744000154405299"),
        ),
        (
            "https://apply.workable.com/huggingface/j/81B46579FE/",
            (AtsType.WORKABLE, "huggingface", "81B46579FE"),
        ),
        (
            "https://bunq.recruitee.com/o/technical-website-intern",
            (AtsType.RECRUITEE, "bunq", "technical-website-intern"),
        ),
        ("https://apply.workable.com/huggingface/", None),
        ("https://careers.bunq.com/o/technical-website-intern", None),  # custom domain: read by the LLM
    ],
)
def test_new_board_links_are_recognised(url: str, expected: tuple[AtsType, str, str] | None) -> None:
    from app.services.sources.manual import parse_ats_url

    link = parse_ats_url(url)
    assert (None if link is None else (link.ats, link.token, link.job_id)) == expected


@respx.mock
async def test_a_pasted_board_link_needs_no_llm(http: PoliteHttpClient) -> None:
    from app.services.llm.fake import FakeLLMClient
    from app.services.sources.manual import ManualJobResolver

    respx.get("https://bunq.recruitee.com/api/offers/").mock(
        return_value=httpx.Response(200, json=load("recruitee/board_bunq.json"))
    )
    respx.get(f"{SR_BOARD}/744000154405299").mock(
        return_value=httpx.Response(200, json=load("smartrecruiters/job_freshworks.json"))
    )
    llm = FakeLLMClient()
    resolver = ManualJobResolver(http, llm)
    intern = await resolver.resolve("https://bunq.recruitee.com/o/technical-website-intern", None)
    assert (intern.job.title, intern.job.source, intern.job.external_id) == (
        "Technical Website Intern",
        JobSourceType.MANUAL,
        "recruitee:technical-website-intern",
    )
    sr = await resolver.resolve(
        "https://jobs.smartrecruiters.com/Freshworks/744000154405299-lead-software-engineer-systems", None
    )
    assert (sr.job.company_name, sr.job.title) == ("Freshworks", "Lead Software Engineer - Systems")
    assert llm.calls == []
