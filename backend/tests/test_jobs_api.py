"""Phase 2: jobs feed (age limit, filters), manual URL add (Greenhouse and Lever fixtures), admin."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, Job, User, UserCompanyBlock
from app.models.enums import AtsType, JobSourceType
from app.services.llm.fake import FakeLLMClient
from app.services.registry import get_source_http
from app.services.sources.http import PoliteHttpClient
from app.services.sources.manual import AtsLink, parse_ats_url
from tests.conftest import FIXTURES

SOURCES = FIXTURES / "sources"


def load(path: str) -> Any:
    return json.loads((SOURCES / path).read_text())


@pytest.fixture(autouse=True)
def fast_http() -> Iterator[None]:
    from app.main import app

    async def no_sleep(_: float) -> None:
        return None

    app.dependency_overrides[get_source_http] = lambda: PoliteHttpClient(
        min_interval_seconds=0, sleep=no_sleep
    )
    yield
    app.dependency_overrides.pop(get_source_http, None)


async def _job(
    session: AsyncSession,
    company: Company,
    title: str,
    *,
    posted_days_ago: int | None,
    seen_days_ago: int = 0,
    active: bool = True,
    employment_type: str | None = None,
    remote: bool | None = None,
) -> Job:
    now = datetime.now(UTC)
    job = Job(
        company_id=company.id,
        source=JobSourceType.GREENHOUSE,
        title=title,
        location="Bengaluru",
        dedupe_hash=f"{company.name}-{title}",
        posted_at=now - timedelta(days=posted_days_ago) if posted_days_ago is not None else None,
        first_seen_at=now - timedelta(days=seen_days_ago),
        is_active=active,
        employment_type=employment_type,
        remote=remote,
    )
    session.add(job)
    await session.flush()
    return job


@pytest.fixture
async def feed_data(session: AsyncSession) -> dict[str, Company]:
    acme = Company(name="Acme", domain="acme.example")
    blocked = Company(name="Blocked Co", domain="blocked.example")
    session.add_all([acme, blocked])
    await session.flush()
    await _job(session, acme, "Fresh Backend Intern", posted_days_ago=2, employment_type="internship")
    await _job(session, acme, "Remote SWE", posted_days_ago=5, employment_type="full_time", remote=True)
    await _job(session, acme, "Old Posting", posted_days_ago=30)
    await _job(session, acme, "No Date Recently Seen", posted_days_ago=None, seen_days_ago=1)
    await _job(session, acme, "No Date Seen Long Ago", posted_days_ago=None, seen_days_ago=20)
    await _job(session, acme, "Closed Posting", posted_days_ago=1, active=False)
    await _job(session, blocked, "Job At Blocked Co", posted_days_ago=1)
    await session.commit()
    return {"acme": acme, "blocked": blocked}


async def test_feed_excludes_old_inactive_and_blocked(
    auth_client: AsyncClient, session: AsyncSession, feed_data: dict[str, Company]
) -> None:
    user = (await session.execute(select(User))).scalar_one()
    session.add(UserCompanyBlock(user_id=user.id, company_id=feed_data["blocked"].id))
    await session.commit()

    body = (await auth_client.get("/jobs")).json()
    titles = [j["title"] for j in body["items"]]
    assert body["max_age_days"] == 14
    # Newest first; age uses posted_at, else first_seen_at.
    assert titles == ["No Date Recently Seen", "Fresh Backend Intern", "Remote SWE"]
    assert body["total"] == 3
    item = body["items"][1]
    assert item["company"]["name"] == "Acme"
    assert item["age_days"] == 2


async def test_feed_respects_user_max_age_and_cannot_widen_it(
    auth_client: AsyncClient, feed_data: dict[str, Company]
) -> None:
    prefs = (await auth_client.get("/preferences")).json() | {"max_job_age_days": 3}
    await auth_client.put("/preferences", json=prefs)
    titles = [j["title"] for j in (await auth_client.get("/jobs")).json()["items"]]
    assert "Remote SWE" not in titles  # 5 days old > 3
    widened = (await auth_client.get("/jobs", params={"max_age_days": 30})).json()
    assert widened["max_age_days"] == 3
    assert "Old Posting" not in [j["title"] for j in widened["items"]]
    # Narrowing works: 2 days keeps only the 1-day-old jobs (the intern post is 2 days old).
    narrowed = (await auth_client.get("/jobs", params={"max_age_days": 2})).json()
    assert {j["title"] for j in narrowed["items"]} == {"No Date Recently Seen", "Job At Blocked Co"}


async def test_feed_filters(auth_client: AsyncClient, feed_data: dict[str, Company]) -> None:
    async def titles(**params: object) -> list[str]:
        return [j["title"] for j in (await auth_client.get("/jobs", params=params)).json()["items"]]

    assert await titles(employment_type="internship") == ["Fresh Backend Intern"]
    assert await titles(remote="true") == ["Remote SWE"]
    assert await titles(q="intern") == ["Fresh Backend Intern"]
    assert await titles(q="acme", limit=1, offset=1) == ["Fresh Backend Intern"]


async def test_feed_requires_auth(client: AsyncClient) -> None:
    assert (await client.get("/jobs")).status_code == 401
    assert (await client.post("/jobs/manual", json={"url": "https://example.com"})).status_code == 401


# --- manual add ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://boards.greenhouse.io/figma/jobs/5426468004",
            AtsLink(AtsType.GREENHOUSE, "figma", "5426468004"),
        ),
        (
            "https://job-boards.greenhouse.io/figma/jobs/5426468004?gh_jid=1",
            AtsLink(AtsType.GREENHOUSE, "figma", "5426468004"),
        ),
        (
            "https://boards.greenhouse.io/embed/job_app?for=figma&token=5426468004",
            AtsLink(AtsType.GREENHOUSE, "figma", "5426468004"),
        ),
        (
            "https://jobs.lever.co/cred/aa98a938-af3a-45f5-851d-966b2b5bad33/apply",
            AtsLink(AtsType.LEVER, "cred", "aa98a938-af3a-45f5-851d-966b2b5bad33"),
        ),
        (
            "https://jobs.ashbyhq.com/sarvam/f3376204-1c2d-42a8-bf4a-1a0eec2fbc3c",
            AtsLink(AtsType.ASHBY, "sarvam", "f3376204-1c2d-42a8-bf4a-1a0eec2fbc3c"),
        ),
        ("https://careers.example.com/jobs/123", None),
        ("https://jobs.lever.co/cred", None),
    ],
)
def test_parse_ats_url(url: str, expected: AtsLink | None) -> None:
    assert parse_ats_url(url) == expected


@respx.mock
async def test_manual_add_greenhouse_job(
    with_llm_key: AsyncClient, fake_llm: FakeLLMClient, session: AsyncSession
) -> None:
    job = load("greenhouse/job_figma.json")
    respx.get(f"https://boards-api.greenhouse.io/v1/boards/figma/jobs/{job['id']}").mock(
        return_value=httpx.Response(200, json=job)
    )
    url = f"https://boards.greenhouse.io/figma/jobs/{job['id']}"
    response = await with_llm_key.post("/jobs/manual", json={"url": url})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["title"] == job["title"]
    assert body["company"]["name"] == "Figma"
    assert body["source"] == "manual"
    assert len(fake_llm.calls) == 1  # only the key verification: ATS links need no LLM

    company = await session.scalar(select(Company).where(Company.ats_token == "figma"))
    assert company is not None
    assert company.ats_type == AtsType.GREENHOUSE

    # Adding it again doesn't duplicate the job.
    again = await with_llm_key.post("/jobs/manual", json={"url": url})
    assert again.json()["id"] == body["id"]


@respx.mock
async def test_manual_add_lever_job(with_llm_key: AsyncClient, fake_llm: FakeLLMClient) -> None:
    job = load("lever/job_cred.json")
    respx.get(f"https://api.lever.co/v0/postings/cred/{job['id']}").mock(
        return_value=httpx.Response(200, json=job)
    )
    response = await with_llm_key.post(
        "/jobs/manual", json={"url": f"https://jobs.lever.co/cred/{job['id']}"}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["title"] == job["text"]
    assert body["employment_type"] == "full_time"
    assert body["url"] == job["hostedUrl"]


@respx.mock
async def test_manual_add_unknown_ats_job_is_404(with_llm_key: AsyncClient) -> None:
    respx.get("https://boards-api.greenhouse.io/v1/boards/figma/jobs/1").mock(
        return_value=httpx.Response(404)
    )
    response = await with_llm_key.post(
        "/jobs/manual", json={"url": "https://boards.greenhouse.io/figma/jobs/1"}
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "job_fetch_failed"


CAREERS_PAGE = """<html><head><title>Backend Intern | Example Robotics Careers</title></head><body>
<nav>Home Products Careers</nav><main><article><h1>Backend Intern</h1>
<p>Example Robotics builds warehouse robots. We're hiring a backend intern in Bengaluru to build Python services
backed by PostgreSQL, working with our platform team on APIs, data pipelines and the fleet dashboard.</p>
<p>Requirements: Python, SQL, curiosity. Six-month internship, stipend provided. Contact hr@example-robotics.com.</p>
</article></main><footer>(c) Example Robotics</footer></body></html>"""


@respx.mock
async def test_manual_add_generic_page_uses_llm(with_llm_key: AsyncClient, fake_llm: FakeLLMClient) -> None:
    respx.get("https://careers.example-robotics.com/jobs/backend-intern").mock(
        return_value=httpx.Response(
            200, text=CAREERS_PAGE, headers={"content-type": "text/html; charset=utf-8"}
        )
    )
    fake_llm.add_response(
        "parse_job_page",
        {
            "is_job_posting": True,
            "company": "Example Robotics",
            "title": "Backend Intern",
            "location": "Bengaluru",
            "remote": False,
            "employment_type": "internship",
        },
    )
    response = await with_llm_key.post(
        "/jobs/manual", json={"url": "https://careers.example-robotics.com/jobs/backend-intern"}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["company"]["domain"] == "example-robotics.com"
    assert body["employment_type"] == "internship"
    request, prompt = fake_llm.calls[-1]
    assert request.prompt_name == "parse_job_page"
    assert request.api_key == "AIza-test-key-1234567890"  # the user's key
    assert "hr@example-robotics.com" not in prompt


@respx.mock
async def test_manual_add_non_job_page_is_422(with_llm_key: AsyncClient, fake_llm: FakeLLMClient) -> None:
    respx.get("https://example.com/blog/post").mock(
        return_value=httpx.Response(200, text=CAREERS_PAGE, headers={"content-type": "text/html"})
    )
    fake_llm.add_response("parse_job_page", {"is_job_posting": False})
    response = await with_llm_key.post("/jobs/manual", json={"url": "https://example.com/blog/post"})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "not_a_job"


# --- admin --------------------------------------------------------------------------------------------


async def test_admin_routes_need_admin(auth_client: AsyncClient, other_user_headers: dict[str, str]) -> None:
    auth_client.cookies.clear()
    for method, path in [("GET", "/admin/companies"), ("POST", "/admin/companies"), ("POST", "/admin/poll")]:
        assert (await auth_client.request(method, path, headers=other_user_headers)).status_code == 403


@respx.mock
async def test_admin_adds_company_after_verifying_board(auth_client: AsyncClient) -> None:
    respx.get("https://api.ashbyhq.com/posting-api/job-board/sarvam").mock(
        return_value=httpx.Response(200, json=load("ashby/board_sarvam.json"))
    )
    body = {
        "name": "Sarvam AI",
        "domain": "https://www.sarvam.ai/",
        "ats_type": "ashby",
        "ats_token": "sarvam",
        "size_hint": "startup",
    }
    response = await auth_client.post("/admin/companies", json=body)
    assert response.status_code == 201, response.text
    assert response.json()["domain"] == "sarvam.ai"
    assert response.json()["jobs_on_board"] == 3

    assert (await auth_client.post("/admin/companies", json=body)).status_code == 409
    listed = (await auth_client.get("/admin/companies")).json()
    assert [c["name"] for c in listed] == ["Sarvam AI"]


@respx.mock
async def test_admin_rejects_unknown_board(auth_client: AsyncClient) -> None:
    respx.get("https://boards-api.greenhouse.io/v1/boards/nope/jobs").mock(return_value=httpx.Response(404))
    response = await auth_client.post(
        "/admin/companies", json={"name": "Nope", "ats_type": "greenhouse", "ats_token": "nope"}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "ats_board_not_found"


async def test_admin_poll_enqueues_worker_job(
    auth_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    enqueued: list[str] = []

    class Pool:
        async def enqueue_job(self, name: str, **_: object) -> object:
            enqueued.append(name)
            return type("Job", (), {"job_id": "poll_sources:manual"})()

        async def aclose(self) -> None:
            return None

    async def fake_pool(*_: object, **__: object) -> Pool:
        return Pool()

    monkeypatch.setattr("app.api.routes.admin.create_pool", fake_pool)
    response = await auth_client.post("/admin/poll")
    assert response.status_code == 202
    assert enqueued == ["poll_sources"]
