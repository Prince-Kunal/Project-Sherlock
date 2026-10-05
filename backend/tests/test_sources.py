"""Phase 2: fixture-based normalisation tests for every adapter, including missing fields.
Fixtures are real API responses (tests/fixtures/record_sources.py), except Adzuna (see its __note)."""

import copy
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx
from fakeredis import FakeAsyncRedis

from app.models.enums import AtsType, JobSourceType
from app.services.llm.fake import FakeLLMClient
from app.services.sources.adzuna import AdzunaNotConfiguredError, AdzunaSource
from app.services.sources.ashby import AshbySource
from app.services.sources.base import CompanyRef, JobQuery, MalformedJobError, RawJob
from app.services.sources.greenhouse import GreenhouseSource
from app.services.sources.hn import HNSource, company_domain_from_url
from app.services.sources.http import PoliteHttpClient
from app.services.sources.lever import LeverSource
from tests.conftest import FIXTURES, recorded

SOURCES = FIXTURES / "sources"


def load(path: str) -> Any:
    return json.loads((SOURCES / path).read_text())


async def _no_sleep(_: float) -> None:
    return None


@pytest.fixture
def http() -> PoliteHttpClient:
    return PoliteHttpClient(min_interval_seconds=0, sleep=_no_sleep)


def ref(ats: AtsType, token: str, name: str = "Co", domain: str | None = "co.example") -> CompanyRef:
    return CompanyRef(id=uuid.uuid4(), name=name, domain=domain, ats_type=ats, ats_token=token)


# --- Greenhouse --------------------------------------------------------------------------------------


@respx.mock
async def test_greenhouse_fetch_and_normalize(http: PoliteHttpClient) -> None:
    route = respx.get("https://boards-api.greenhouse.io/v1/boards/figma/jobs").mock(
        return_value=httpx.Response(200, json=load("greenhouse/board_figma.json"))
    )
    source = GreenhouseSource(http)
    raws = await source.fetch(ref(AtsType.GREENHOUSE, "figma", "Figma", "figma.com"))
    assert route.calls.last.request.url.params["content"] == "true"
    jobs = [source.normalize(r) for r in raws]

    assert len(jobs) == 3
    job = jobs[1]
    assert job.source == JobSourceType.GREENHOUSE
    assert job.company_name == "Figma"
    assert job.company_domain == "figma.com"
    assert job.location == "Bengaluru, India"
    assert job.url
    assert job.url.startswith("https://boards.greenhouse.io/figma/jobs/")
    # first_published becomes posted_at (deviation from the plan, agreed 2026-10-05).
    assert job.posted_at == datetime.fromisoformat("2025-07-21T23:53:16-04:00")
    # Double-encoded HTML content is decoded and stripped.
    assert "Figma is growing our team" in job.description_text
    assert "&lt;" not in job.description_text
    assert "<p>" not in job.description_text
    assert len(job.description_text) <= 12_000


def test_greenhouse_missing_fields() -> None:
    source = GreenhouseSource(http=None)  # type: ignore[arg-type]
    job = copy.deepcopy(load("greenhouse/board_figma.json")["jobs"][0])
    for key in ("first_published", "location", "content", "absolute_url", "metadata"):
        job.pop(key)
    out = source.normalize(
        RawJob(source=JobSourceType.GREENHOUSE, external_id="1", payload=job, company_name="Figma")
    )
    assert out.posted_at is None  # falls back to first_seen_at at upsert time
    assert out.location is None
    assert out.description_text == ""
    assert out.url is None

    job["title"] = "   "
    with pytest.raises(MalformedJobError):
        source.normalize(RawJob(source=JobSourceType.GREENHOUSE, external_id="1", payload=job))


@pytest.mark.parametrize(
    ("name", "metadata", "location", "remote"),
    [
        # Cloudflare's real shape: location.name is the arrangement, places are in custom metadata.
        (
            "Hybrid",
            [{"name": "Job Posting Location", "value": ["Bengaluru, India"]}],
            "Bengaluru, India (Hybrid)",
            False,
        ),
        (
            "Distributed",
            [{"name": "Job Posting Location", "value": ["Austin, US", "New York, US"]}],
            "Austin, US | New York, US (Distributed)",
            True,
        ),
        ("Hybrid", [], "Hybrid", False),  # nothing better known
        ("London, UK", [{"name": "Job Posting Location", "value": ["Paris"]}], "London, UK", None),
    ],
)
def test_greenhouse_location_from_metadata_when_name_is_an_arrangement(
    name: str, metadata: list[dict[str, Any]], location: str, remote: bool | None
) -> None:
    source = GreenhouseSource(http=None)  # type: ignore[arg-type]
    job = copy.deepcopy(load("greenhouse/board_figma.json")["jobs"][0])
    job["location"] = {"name": name}
    job["metadata"] = metadata
    out = source.normalize(
        RawJob(source=JobSourceType.GREENHOUSE, external_id="1", payload=job, company_name="Cloudflare")
    )
    assert (out.location, out.remote) == (location, remote)


# --- Lever --------------------------------------------------------------------------------------------


@respx.mock
async def test_lever_fetch_and_normalize(http: PoliteHttpClient) -> None:
    respx.get("https://api.lever.co/v0/postings/cred").mock(
        return_value=httpx.Response(200, json=load("lever/board_cred.json"))
    )
    source = LeverSource(http)
    jobs = [source.normalize(r) for r in await source.fetch(ref(AtsType.LEVER, "cred", "CRED", "cred.club"))]
    assert len(jobs) == 3
    job = jobs[0]
    assert job.title == "accounts payable manager"
    assert job.location == "hyderabad"
    assert job.employment_type == "full_time"  # categories.commitment "full time"
    assert job.remote is False  # workplaceType "onsite"
    assert job.posted_at == datetime.fromtimestamp(1790573982021 / 1000, UTC)  # createdAt (ms)
    assert job.url == "https://jobs.lever.co/cred/aa98a938-af3a-45f5-851d-966b2b5bad33"
    assert "Prefr" in job.description_text


def test_lever_missing_fields() -> None:
    source = LeverSource(http=None)  # type: ignore[arg-type]
    job = copy.deepcopy(load("lever/board_cred.json")[0])
    for key in (
        "categories",
        "createdAt",
        "workplaceType",
        "lists",
        "descriptionPlain",
        "descriptionBodyPlain",
        "description",
        "descriptionBody",
        "opening",
        "openingPlain",
        "additional",
        "additionalPlain",
    ):
        job.pop(key, None)
    out = source.normalize(
        RawJob(source=JobSourceType.LEVER, external_id="x", payload=job, company_name="CRED")
    )
    assert out.location is None
    assert out.posted_at is None
    assert out.remote is None
    assert out.employment_type is None
    assert out.description_text == ""
    job.pop("text")
    with pytest.raises(MalformedJobError):
        source.normalize(RawJob(source=JobSourceType.LEVER, external_id="x", payload=job))


def test_lever_intern_title_wins_over_commitment() -> None:
    source = LeverSource(http=None)  # type: ignore[arg-type]
    job = copy.deepcopy(load("lever/board_cred.json")[0])
    job["text"] = "Backend Engineering Intern"
    out = source.normalize(
        RawJob(source=JobSourceType.LEVER, external_id="x", payload=job, company_name="CRED")
    )
    assert out.employment_type == "internship"


# --- Ashby --------------------------------------------------------------------------------------------


@respx.mock
async def test_ashby_fetch_skips_unlisted_and_normalizes(http: PoliteHttpClient) -> None:
    board = load("ashby/board_sarvam.json")
    board["jobs"][2]["isListed"] = False
    respx.get("https://api.ashbyhq.com/posting-api/job-board/sarvam").mock(
        return_value=httpx.Response(200, json=board)
    )
    source = AshbySource(http)
    jobs = [source.normalize(r) for r in await source.fetch(ref(AtsType.ASHBY, "sarvam", "Sarvam AI"))]
    assert [j.title for j in jobs] == ["Solution Specialist", "Engagement Manager, Chanakya"]
    job = jobs[0]
    assert job.location == "Bengaluru"
    assert job.employment_type == "full_time"  # employmentType "FullTime"
    assert job.remote is False  # isRemote false
    assert job.posted_at == datetime.fromisoformat("2026-05-20T08:44:45.357+00:00")
    assert job.url == "https://jobs.ashbyhq.com/sarvam/f3376204-1c2d-42a8-bf4a-1a0eec2fbc3c"


def test_ashby_missing_fields_and_secondary_locations() -> None:
    source = AshbySource(http=None)  # type: ignore[arg-type]
    job = copy.deepcopy(load("ashby/board_sarvam.json")["jobs"][0])
    for key in (
        "publishedAt",
        "employmentType",
        "isRemote",
        "workplaceType",
        "descriptionPlain",
        "descriptionHtml",
    ):
        job.pop(key)
    job["secondaryLocations"] = [{"location": "Remote - India"}, {"location": "Bengaluru"}]
    out = source.normalize(
        RawJob(source=JobSourceType.ASHBY, external_id="a", payload=job, company_name="Sarvam")
    )
    assert out.location == "Bengaluru / Remote - India"
    assert out.remote is True  # inferred from the location text
    assert out.posted_at is None
    assert out.employment_type is None
    assert out.description_text == ""


# --- Adzuna -------------------------------------------------------------------------------------------


@respx.mock
async def test_adzuna_fetch_and_normalize(http: PoliteHttpClient) -> None:
    route = respx.get("https://api.adzuna.com/v1/api/jobs/in/search/1").mock(
        return_value=httpx.Response(200, json=load("adzuna/search_in.json"))
    )
    source = AdzunaSource(http, "app-id", "app-key")
    raws = await source.fetch(JobQuery(what="backend intern"))
    params = route.calls.last.request.url.params
    assert params["what"] == "backend intern"
    assert params["max_days_old"] == "14"
    assert params["app_id"] == "app-id"
    jobs = [source.normalize(r) for r in raws]
    assert len(jobs) == 4
    assert jobs[0].title == "Software Development Engineer – Intern / Fresher"  # mojibake repaired
    assert jobs[0].company_name == "Mellow Vault"
    assert jobs[0].location == "Noida, Ghaziabad"
    assert jobs[0].employment_type == "internship"  # title beats contract_time=full_time
    assert jobs[0].posted_at == datetime(2026, 10, 4, 16, 36, 40, tzinfo=UTC)
    assert jobs[0].company_domain is None  # unknown until Phase 5
    assert (jobs[0].url or "").startswith("https://www.adzuna.in/details/")
    assert jobs[1].employment_type == "full_time"  # contract_time
    assert jobs[3].employment_type == "internship"
    assert jobs[3].company_name == "Procter & Gamble"


async def test_adzuna_requires_keys(http: PoliteHttpClient) -> None:
    source = AdzunaSource(http, "", "")
    assert not source.configured
    with pytest.raises(AdzunaNotConfiguredError):
        await source.fetch(JobQuery(what="intern"))


def test_adzuna_result_without_company_is_skipped() -> None:
    source = AdzunaSource(http=None, app_id="a", app_key="b")  # type: ignore[arg-type]
    result = load("adzuna/search_in.json")["results"][0]
    with pytest.raises(MalformedJobError):
        source.normalize(
            RawJob(source=JobSourceType.ADZUNA, external_id="1", payload=result, company_name=None)
        )


# --- HN -----------------------------------------------------------------------------------------------


def _mock_hn() -> None:
    respx.get("https://hn.algolia.com/api/v1/search_by_date").mock(
        return_value=httpx.Response(200, json=load("hn/search.json"))
    )
    thread = load("hn/thread.json")
    respx.get(f"https://hn.algolia.com/api/v1/items/{thread['id']}").mock(
        return_value=httpx.Response(200, json=thread)
    )


@respx.mock
async def test_hn_parses_relevant_comments_once(http: PoliteHttpClient) -> None:
    _mock_hn()
    thread = load("hn/thread.json")
    thread["children"][0]["text"] += "<p>Questions? Write to hiring@prairielearn.example</p>"
    respx.get(f"https://hn.algolia.com/api/v1/items/{thread['id']}").mock(
        return_value=httpx.Response(200, json=thread)
    )
    llm = FakeLLMClient({"parse_hn_comment": [recorded("parse_hn_comment", "thread")]})
    redis = FakeAsyncRedis(decode_responses=True)
    source = HNSource(http, llm, redis, keywords=["remote"], batch_size=10, max_requests_per_run=1)

    raws = await source.fetch(None)
    jobs = [source.normalize(r) for r in raws]

    # Only the 4 comments mentioning "remote" were sent, in one batched request, with emails redacted.
    [(request, prompt)] = llm.calls
    sent = json.loads(prompt.split("```json\n")[-1].split("\n```")[0])
    assert len(sent) == 4
    assert "hiring@prairielearn.example" not in prompt
    assert request.api_key is None  # shared work uses the owner's key

    prairie = next(j for j in jobs if j.company_name == "PrairieLearn")
    assert prairie.source == JobSourceType.HN
    assert prairie.remote is True
    assert prairie.source_meta
    assert prairie.source_meta["contact_emails"] == ["hiring@prairielearn.example"]
    assert prairie.posted_at == datetime(2026, 10, 1, 15, 2, 37, tzinfo=UTC)
    # Comments whose text wasn't sent (non-remote ones) produce no jobs even if the LLM mentions them.
    assert {j.company_name for j in jobs} <= {"PrairieLearn", "We The Flywheel", "Sidekick Labs", "PAGNOS"}

    # A second poll finds nothing new to parse: no further LLM calls.
    assert await source.fetch(None) == []
    assert len(llm.calls) == 1


@respx.mock
async def test_hn_respects_request_cap(http: PoliteHttpClient) -> None:
    _mock_hn()
    llm = FakeLLMClient({"parse_hn_comment": [[]]})
    source = HNSource(
        http,
        llm,
        FakeAsyncRedis(decode_responses=True),
        keywords=["remote"],
        batch_size=2,
        max_requests_per_run=1,
    )
    await source.fetch(None)
    assert len(llm.calls) == 1  # 4 relevant comments, batches of 2, but only 1 request allowed
    await source.fetch(None)
    assert len(llm.calls) == 2  # the next poll continues with the remaining 2


@pytest.mark.parametrize(
    ("url", "domain"),
    [
        ("https://www.prairielearn.com/jobs-ashby", "prairielearn.com"),
        ("https://careers.acme.io/backend", "acme.io"),
        ("https://jobs.lever.co/acme/123", None),
        ("https://news.ycombinator.com/item?id=1", None),
        (None, None),
    ],
)
def test_company_domain_from_url(url: str | None, domain: str | None) -> None:
    assert company_domain_from_url(url) == domain
