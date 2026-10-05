"""Matches API (PLAN.md Phase 3): feed defaults, shortlist/hide/restore, company blocks, refresh."""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.redis import get_redis
from app.models import JobMatch, User
from app.models.enums import JobMatchStatus
from app.services.embeddings.fake import FakeEmbedder
from app.services.llm.fake import FakeLLMClient
from app.services.matching.pipeline import Matcher
from tests.conftest import recorded
from tests.matching_fixtures import seed_fixture_jobs, seed_matching_user


async def scored_user(session: AsyncSession, user_id: uuid.UUID) -> dict[str, uuid.UUID]:
    """Give `user_id` the fixture resume, key and prefs, insert the fixture jobs and score them."""
    user = await session.get(User, user_id)
    assert user is not None
    await seed_matching_user(session, user=user)
    ids = await seed_fixture_jobs(session)
    llm = FakeLLMClient(responses={"match": [recorded("match", "fixture_jobs")]})
    settings = get_settings().model_copy(update={"embed_min_sim": 0.0})
    matcher = Matcher(llm=llm, embedder=FakeEmbedder(), redis=get_redis(), settings=settings)
    await matcher.match_user(session, user_id)
    return ids


async def _me(client: AsyncClient) -> uuid.UUID:
    return uuid.UUID((await client.get("/auth/me")).json()["id"])


@pytest.fixture
async def scored(auth_client: AsyncClient, session: AsyncSession) -> dict[str, uuid.UUID]:
    return await scored_user(session, await _me(auth_client))


def _titles(body: dict[str, Any]) -> list[str]:
    return [item["job"]["title"] for item in body["items"]]


async def test_feed_shows_only_good_fits_by_default(
    auth_client: AsyncClient, scored: dict[str, uuid.UUID]
) -> None:
    response = await auth_client.get("/matches")
    assert response.status_code == 200
    body = response.json()
    assert _titles(body) == ["Backend Engineering Intern"]
    assert body["min_score"] == 70
    item = body["items"][0]
    assert item["fit_score"] == max(i["fit_score"] for i in recorded("match", "fixture_jobs"))  # type: ignore[union-attr]
    assert item["status"] == "new"
    assert "postgresql" in item["matched_skills"]
    assert item["reasoning"]
    assert item["job"]["company"]["name"] == "Ledgerline"
    assert body["scoring"] == {"llm_key_configured": True, "calls_last_24h": 1, "daily_limit": 6}


async def test_min_score_lowers_the_bar_but_preferences_still_apply(
    auth_client: AsyncClient, scored: dict[str, uuid.UUID]
) -> None:
    body = (await auth_client.get("/matches", params={"min_score": 0})).json()
    # Best first. The platform job (LLM said full-time) stays out: this user wants internships.
    assert _titles(body) == ["Backend Engineering Intern", "Sales Development Intern"]
    assert body["total"] == 2


async def test_shortlist_hide_restore(auth_client: AsyncClient, scored: dict[str, uuid.UUID]) -> None:
    [item] = (await auth_client.get("/matches")).json()["items"]
    match_id = item["id"]

    response = await auth_client.post(f"/matches/{match_id}/shortlist")
    assert response.status_code == 200
    assert response.json()["status"] == "shortlisted"
    shortlisted = (await auth_client.get("/matches", params={"status": "shortlisted"})).json()
    assert [i["id"] for i in shortlisted["items"]] == [match_id]
    assert len((await auth_client.get("/matches")).json()["items"]) == 1  # active = new + shortlisted

    assert (await auth_client.post(f"/matches/{match_id}/hide")).json()["status"] == "hidden"
    assert (await auth_client.get("/matches")).json()["items"] == []
    hidden = (await auth_client.get("/matches", params={"status": "hidden"})).json()
    assert [i["id"] for i in hidden["items"]] == [match_id]

    assert (await auth_client.post(f"/matches/{match_id}/restore")).json()["status"] == "new"
    assert len((await auth_client.get("/matches")).json()["items"]) == 1


async def test_expired_match_cannot_be_changed(
    auth_client: AsyncClient, session: AsyncSession, scored: dict[str, uuid.UUID]
) -> None:
    await session.execute(
        update(JobMatch).where(JobMatch.job_id == scored["relevant"]).values(status=JobMatchStatus.EXPIRED)
    )
    await session.commit()
    [item] = (await auth_client.get("/matches", params={"status": "expired"})).json()["items"]
    response = await auth_client.post(f"/matches/{item['id']}/shortlist")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "match_locked"


async def test_unknown_match_is_404(auth_client: AsyncClient) -> None:
    response = await auth_client.post(f"/matches/{uuid.uuid4()}/hide")
    assert response.status_code == 404


async def test_blocking_a_company_hides_its_matches(
    auth_client: AsyncClient, scored: dict[str, uuid.UUID]
) -> None:
    [item] = (await auth_client.get("/matches")).json()["items"]
    company_id = item["job"]["company"]["id"]

    response = await auth_client.post(f"/companies/{company_id}/block")
    assert response.status_code == 200
    assert response.json()["blocked"] is True
    assert (await auth_client.post(f"/companies/{company_id}/block")).status_code == 200  # idempotent
    assert (await auth_client.get("/matches")).json()["items"] == []
    assert [c["name"] for c in (await auth_client.get("/companies/blocked")).json()] == ["Ledgerline"]
    # The plain jobs feed hides it too.
    jobs = (await auth_client.get("/jobs")).json()["items"]
    assert all(j["company"]["id"] != company_id for j in jobs)

    assert (await auth_client.delete(f"/companies/{company_id}/block")).status_code == 204
    assert len((await auth_client.get("/matches")).json()["items"]) == 1


async def test_block_unknown_company_is_404(auth_client: AsyncClient) -> None:
    assert (await auth_client.post(f"/companies/{uuid.uuid4()}/block")).status_code == 404


async def test_refresh_enqueues_matching_for_this_user(
    auth_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    enqueued: list[tuple[str, tuple[Any, ...], str | None]] = []

    class Pool:
        async def enqueue_job(self, name: str, *args: Any, _job_id: str | None = None) -> object:
            enqueued.append((name, args, _job_id))
            return type("Job", (), {"job_id": _job_id})()

        async def aclose(self) -> None:
            return None

    async def fake_pool(*_: object, **__: object) -> Pool:
        return Pool()

    monkeypatch.setattr("app.workers.queue.create_pool", fake_pool)
    response = await auth_client.post("/matches/refresh")
    assert response.status_code == 202
    assert response.json() == {"queued": True}
    user_id = str(await _me(auth_client))
    assert enqueued == [("match_jobs_for_users", (user_id,), f"match_jobs:{user_id}")]


async def test_feed_without_key_reports_it(auth_client: AsyncClient) -> None:
    body = (await auth_client.get("/matches")).json()
    assert body["items"] == []
    assert body["scoring"]["llm_key_configured"] is False


async def test_match_routes_require_auth(client: AsyncClient) -> None:
    some_id = uuid.uuid4()
    for method, path in [
        ("GET", "/matches"),
        ("POST", "/matches/refresh"),
        ("POST", f"/matches/{some_id}/shortlist"),
        ("POST", f"/matches/{some_id}/hide"),
        ("POST", f"/matches/{some_id}/restore"),
        ("GET", "/companies/blocked"),
        ("POST", f"/companies/{some_id}/block"),
        ("DELETE", f"/companies/{some_id}/block"),
    ]:
        assert (await client.request(method, path)).status_code == 401, path
