"""Phase 3 acceptance: hard filters + embedding prefilter + LLM rerank rank the fixture jobs correctly
(fake LLM replaying a recorded real response), matching is incremental, and the per-user daily
allowance, per-item re-scoring and quota handling hold."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.redis import get_redis
from app.models import Job, JobMatch, UsageLedger
from app.models.enums import JobMatchStatus
from app.schemas.matches import ScoredJob
from app.services.embeddings.fake import FakeEmbedder
from app.services.llm.client import LLMQuotaExhaustedError, LLMRequest
from app.services.llm.fake import FakeLLMClient
from app.services.matching.embed import embed_missing_jobs
from app.services.matching.filters import location_matches
from app.services.matching.pipeline import UNSCORABLE_REASON, Matcher, expire_matches
from app.services.matching.profile import candidate_payload, profile_text, user_skills
from app.services.matching.rerank import clean_skills
from tests.conftest import recorded
from tests.matching_fixtures import (
    FIXTURE_PREFS,
    SCORED_KEYS,
    fixture_resume,
    seed_fixture_jobs,
    seed_matching_user,
)

RECORDED = cast(list[dict[str, Any]], recorded("match", "fixture_jobs"))


def _settings(**overrides: Any) -> Settings:
    # The fake embedder's bag-of-words similarities are low, so tests open the floor unless they test it.
    return get_settings().model_copy(update={"embed_min_sim": 0.0, **overrides})


def _matcher(llm: FakeLLMClient, **overrides: Any) -> Matcher:
    return Matcher(llm=llm, embedder=FakeEmbedder(), redis=get_redis(), settings=_settings(**overrides))


def _fake(*responses: object) -> FakeLLMClient:
    return FakeLLMClient(responses={"match": list(responses) if responses else [RECORDED]})


async def _ref(session: AsyncSession, job_id: Any) -> str:
    job = await session.get(Job, job_id)
    assert job is not None
    return job.dedupe_hash[:8]


async def _matches(session: AsyncSession) -> dict[Any, JobMatch]:
    rows = await session.scalars(select(JobMatch).execution_options(populate_existing=True))
    return {m.job_id: m for m in rows.all()}


def _match_calls(llm: FakeLLMClient) -> list[tuple[LLMRequest, str]]:
    return [(r, p) for r, p in llm.calls if r.prompt_name == "match"]


# --- Acceptance: ranking ---------------------------------------------------------------------------


async def test_pipeline_ranks_relevant_over_irrelevant_and_drops_wrong_type(session: AsyncSession) -> None:
    user = await seed_matching_user(session)
    ids = await seed_fixture_jobs(session)
    llm = _fake()

    summary = await _matcher(llm).match_user(session, user.id)

    # Hard filters left exactly three jobs, scored in one batched request.
    assert summary.candidates == 3
    assert summary.llm_calls == 1
    assert summary.scored == 3
    matches = await _matches(session)
    assert set(matches) == {ids[k] for k in SCORED_KEYS}
    # Wrong employment type, wrong city and US-only remote never reached the LLM.
    [(_, prompt)] = _match_calls(llm)
    for title in ("Senior Backend Engineer", "Software Engineering Intern", "Backend Intern (Remote)"):
        assert title not in prompt

    scores: dict[str, int] = {}
    for key in SCORED_KEYS:
        score = matches[ids[key]].llm_score
        assert score is not None, key
        scores[key] = score
    assert scores["relevant"] > scores["unknown_type"] > scores["irrelevant"]
    assert scores["relevant"] >= FIXTURE_PREFS.min_fit_score
    assert all(m.embedding_score is not None for m in matches.values())

    relevant = matches[ids["relevant"]]
    assert {"python", "django", "postgresql", "docker"} <= set(relevant.matched_skills)
    assert set(relevant.matched_skills) <= user_skills(fixture_resume())
    assert relevant.reasoning.startswith("You")  # the prompt asks for second person

    # The LLM's employment type fills a job whose type was unknown (rules first, LLM fallback).
    unknown = await session.get(Job, ids["unknown_type"])
    assert unknown is not None
    assert unknown.employment_type == "full_time"


async def test_prompt_contains_no_personal_details(session: AsyncSession) -> None:
    user = await seed_matching_user(session)
    await seed_fixture_jobs(session)
    llm = _fake()
    await _matcher(llm).match_user(session, user.id)
    [(_, prompt)] = _match_calls(llm)
    assert "rohan@example.com" not in prompt
    assert "Rohan Das" not in prompt
    assert '"basics"' not in prompt


# --- Acceptance: incremental -----------------------------------------------------------------------


async def test_rerunning_does_not_rescore_and_new_jobs_are_scored_alone(session: AsyncSession) -> None:
    user = await seed_matching_user(session)
    await seed_fixture_jobs(session, keys=["relevant", "irrelevant"])
    llm = _fake()
    matcher = _matcher(llm)

    await matcher.match_user(session, user.id)
    first = await _matches(session)
    assert len(first) == 2
    assert len(_match_calls(llm)) == 1

    again = await matcher.match_user(session, user.id)
    assert again.candidates == 0
    assert again.llm_calls == 0
    assert len(_match_calls(llm)) == 1
    assert {k: m.llm_score for k, m in (await _matches(session)).items()} == {
        k: m.llm_score for k, m in first.items()
    }

    # A newly polled job is the only one sent next time.
    ids = await seed_fixture_jobs(session, keys=["unknown_type"])
    await matcher.match_user(session, user.id)
    _, prompt = _match_calls(llm)[-1]
    assert await _ref(session, ids["unknown_type"]) in prompt
    assert "Sales Development Intern" not in prompt
    assert len(await _matches(session)) == 3


# --- Per-item re-scoring -----------------------------------------------------------------------------


async def test_invalid_item_is_rescored_on_its_own(session: AsyncSession) -> None:
    user = await seed_matching_user(session)
    ids = await seed_fixture_jobs(session, keys=SCORED_KEYS)
    relevant_ref = await _ref(session, ids["relevant"])
    batch = [dict(item) for item in RECORDED]
    for item in batch:
        if item["job_ref"] == relevant_ref:
            item["fit_score"] = 150  # out of range: this item alone fails validation
    single = [{**next(i for i in RECORDED if i["job_ref"] == relevant_ref), "fit_score": 88}]
    llm = _fake(batch, single)

    summary = await _matcher(llm).match_user(session, user.id)

    assert summary.llm_calls == 2
    assert summary.scored == 3
    calls = _match_calls(llm)
    retry_prompt = calls[1][1]
    assert relevant_ref in retry_prompt
    for key in ("irrelevant", "unknown_type"):
        assert await _ref(session, ids[key]) not in retry_prompt
    assert (await _matches(session))[ids["relevant"]].llm_score == 88


async def test_item_failing_alone_too_is_recorded_unscored(session: AsyncSession) -> None:
    user = await seed_matching_user(session)
    ids = await seed_fixture_jobs(session, keys=SCORED_KEYS)
    relevant_ref = await _ref(session, ids["relevant"])
    without_relevant = [i for i in RECORDED if i["job_ref"] != relevant_ref]
    llm = _fake(without_relevant, [])  # missing from the batch, then nothing on its own

    summary = await _matcher(llm).match_user(session, user.id)

    assert summary.scored == 2
    assert summary.unscorable == 1
    relevant = (await _matches(session))[ids["relevant"]]
    assert relevant.llm_score is None
    assert relevant.reasoning == UNSCORABLE_REASON
    # It's recorded, so later runs don't keep paying for it.
    again = await _matcher(llm).match_user(session, user.id)
    assert again.llm_calls == 0


def test_clean_skills_keeps_only_skills_the_user_has() -> None:
    result = ScoredJob(
        job_ref="x",
        fit_score=80,
        employment_type="internship",
        matched_skills=["Python", "postgres", "Kubernetes"],  # the user lacks Kubernetes
        missing_must_haves=["Go", "Django", "go"],  # the user has Django
        reasoning="ok",
    )
    matched, missing = clean_skills(result, {"python", "postgresql", "django"})
    assert matched == ["python", "postgresql"]
    assert missing == ["go"]


# --- Budget and failures ----------------------------------------------------------------------------


async def test_daily_allowance_caps_llm_calls_and_is_logged(session: AsyncSession) -> None:
    user = await seed_matching_user(session)
    await seed_fixture_jobs(session, keys=SCORED_KEYS)
    llm = _fake()
    matcher = _matcher(llm, match_daily_llm_calls=1, match_batch_size=1)

    summary = await matcher.match_user(session, user.id)
    assert summary.llm_calls == 1
    assert summary.stopped == "daily_allowance"
    # Batches of one job; the recorded response holds all three, of which the batch's own is kept.
    assert len(await _matches(session)) == 1
    ledger = (await session.scalars(select(UsageLedger))).all()
    assert [(row.operation, row.units, row.user_id) for row in ledger] == [("match_jobs", 1, user.id)]

    # The allowance is per rolling 24h: the next run makes no calls; the run after a day does.
    assert (await matcher.match_user(session, user.id)).llm_calls == 0
    await session.execute(update(UsageLedger).values(created_at=datetime.now(UTC) - timedelta(hours=25)))
    await session.commit()
    assert (await matcher.match_user(session, user.id)).llm_calls == 1


async def test_user_without_key_is_skipped(session: AsyncSession) -> None:
    user = await seed_matching_user(session, with_key=False)
    await seed_fixture_jobs(session)
    llm = _fake()
    summary = await _matcher(llm).match_user(session, user.id)
    assert summary.stopped == "no_llm_key"
    assert _match_calls(llm) == []
    assert await _matches(session) == {}


async def test_quota_exhaustion_stops_but_keeps_finished_batches(session: AsyncSession) -> None:
    class QuotaAfterFirstCall(FakeLLMClient):
        async def _complete_json(self, request: LLMRequest, prompt: str, schema: dict[str, Any]) -> str:
            if len(self.calls) >= 1:
                raise LLMQuotaExhaustedError("daily quota")
            return await super()._complete_json(request, prompt, schema)

    user = await seed_matching_user(session)
    await seed_fixture_jobs(session, keys=SCORED_KEYS)
    llm = QuotaAfterFirstCall(responses={"match": [RECORDED]})
    summary = await _matcher(llm, match_batch_size=1).match_user(session, user.id)
    assert summary.stopped == "LLMQuotaExhaustedError"
    assert len(await _matches(session)) == 1


async def test_user_without_resume_is_skipped(session: AsyncSession) -> None:
    from app.models import User

    user = User(email="new@example.com", name="New")
    session.add(user)
    await session.commit()
    summary = await _matcher(_fake()).match_user(session, user.id)
    assert summary.stopped == "no_resume"


async def test_similarity_floor_drops_dissimilar_jobs(session: AsyncSession) -> None:
    user = await seed_matching_user(session)
    await seed_fixture_jobs(session)
    llm = _fake()
    summary = await _matcher(llm, embed_min_sim=0.99).match_user(session, user.id)
    assert summary.candidates == 0
    assert _match_calls(llm) == []


async def test_match_all_covers_every_user_with_a_resume(session: AsyncSession) -> None:
    from app.core.db import get_sessionmaker
    from app.models import User

    await seed_matching_user(session, email="a@example.com")
    await seed_matching_user(session, email="b@example.com")
    session.add(User(email="no-resume@example.com", name="No resume"))
    await session.commit()
    await seed_fixture_jobs(session, keys=SCORED_KEYS)

    run = await _matcher(_fake()).match_all(get_sessionmaker())
    assert run.users == 2
    # The first user's run learned that the platform job is full-time, so the second user's
    # internship-only hard filter drops it before any LLM call.
    assert run.scored == 3 + 2
    assert await session.scalar(select(func.count()).select_from(JobMatch)) == 5


# --- Embeddings --------------------------------------------------------------------------------------


async def test_embed_missing_jobs_embeds_only_recent_active_jobs_once(session: AsyncSession) -> None:
    now = datetime.now(UTC)
    ids = await seed_fixture_jobs(session, keys=["relevant", "irrelevant", "unknown_type"])
    await session.execute(
        update(Job).where(Job.id == ids["irrelevant"]).values(posted_at=now - timedelta(days=40))
    )
    await session.execute(update(Job).where(Job.id == ids["unknown_type"]).values(is_active=False))
    await session.commit()

    assert await embed_missing_jobs(session, FakeEmbedder(), now=now) == 1
    assert await embed_missing_jobs(session, FakeEmbedder(), now=now) == 0
    session.expire_all()
    relevant = await session.get(Job, ids["relevant"])
    assert relevant is not None
    assert relevant.embedding is not None
    assert len(relevant.embedding) == 384


def test_profile_text_has_roles_skills_and_bullets_but_no_contact_details() -> None:
    text = profile_text(["Backend Engineer Intern"], fixture_resume())
    assert text.startswith("Target roles: Backend Engineer Intern")
    assert "django" in text
    assert "rohan@example.com" not in text
    payload = json.dumps(candidate_payload(FIXTURE_PREFS, fixture_resume()))
    assert "rohan@example.com" not in payload
    assert "Rohan Das" not in payload


# --- Expiry ------------------------------------------------------------------------------------------


async def test_expire_matches(session: AsyncSession) -> None:
    user = await seed_matching_user(session)
    ids = await seed_fixture_jobs(session, keys=SCORED_KEYS)
    await _matcher(_fake()).match_user(session, user.id)
    now = datetime.now(UTC)

    # closed job → expired; too-old shortlisted job → expired; in-pipeline is left alone.
    await session.execute(update(Job).where(Job.id == ids["relevant"]).values(is_active=False))
    await session.execute(
        update(Job).where(Job.id == ids["irrelevant"]).values(posted_at=now - timedelta(days=30))
    )
    await session.execute(
        update(JobMatch).where(JobMatch.job_id == ids["irrelevant"]).values(status=JobMatchStatus.SHORTLISTED)
    )
    await session.execute(
        update(JobMatch)
        .where(JobMatch.job_id == ids["unknown_type"])
        .values(status=JobMatchStatus.IN_PIPELINE)
    )
    await session.execute(update(Job).where(Job.id == ids["unknown_type"]).values(is_active=False))
    await session.commit()

    assert await expire_matches(session, now) == 2
    await session.commit()
    statuses = {k: m.status for k, m in (await _matches(session)).items()}
    assert statuses == {
        ids["relevant"]: JobMatchStatus.EXPIRED,
        ids["irrelevant"]: JobMatchStatus.EXPIRED,
        ids["unknown_type"]: JobMatchStatus.IN_PIPELINE,
    }


# --- Seniority rule ---------------------------------------------------------------------------------


async def test_internship_seekers_skip_senior_titles_of_unknown_type(session: AsyncSession) -> None:
    from app.models import Company
    from app.services.matching.filters import hard_filter_conditions

    company = Company(name="Acme", domain="acme.example")
    session.add(company)
    await session.flush()
    titles = {
        "Senior Software Engineer": None,
        "Sr. Backend Developer": None,
        "Staff Engineer, Platform": None,
        "Software Engineer III": None,
        "SDE-2, Payments": None,
        "Software Engineer 3 - Infra": None,
        "Engineering Manager": None,
        "Software Engineer": None,  # unknown level: kept for the LLM
        "Backend Developer (2026 graduates)": None,
        "Lead Generation Intern": "internship",  # typed internships are never dropped by title
    }
    for i, (title, kind) in enumerate(titles.items()):
        session.add(
            Job(
                company_id=company.id,
                source="manual",
                title=title,
                employment_type=kind,
                dedupe_hash=f"{i:064d}",
            )
        )
    await session.commit()
    user_id = (await seed_matching_user(session)).id

    async def kept(types: list[str]) -> set[str]:
        conditions = hard_filter_conditions(
            user_id, max_job_age_days=14, employment_types=types, company_stages=[], now=datetime.now(UTC)
        )
        return set((await session.scalars(select(Job.title).where(*conditions))).all())

    assert await kept(["internship"]) == {
        "Software Engineer",
        "Backend Developer (2026 graduates)",
        "Lead Generation Intern",
    }
    # Someone open to full-time roles sees every level; scoring judges seniority.
    assert len(await kept(["internship", "full_time"])) == len(titles)


# --- Location rules ----------------------------------------------------------------------------------

BLR = ["Bangalore"]


@pytest.mark.parametrize(
    ("location", "remote", "preferred", "remote_ok", "expected"),
    [
        ("Bengaluru, Karnataka, India", None, BLR, False, True),  # alias
        ("Bangalore", False, ["Bengaluru"], False, True),
        ("San Francisco, CA | Bengaluru, India", None, BLR, False, True),  # one of several
        ("San Francisco, CA", None, BLR, True, False),
        ("Hybrid", None, BLR, False, True),  # unknown place passes
        (None, None, BLR, False, True),
        ("Remote", True, BLR, True, True),
        ("Remote", True, BLR, False, False),
        ("Remote - USA", True, BLR, True, False),  # remote, but tied to another region
        ("San Francisco", True, BLR, True, False),
        ("Remote - India", True, BLR, True, True),
        ("Remote, APAC", True, BLR, True, True),
        ("Remote - India", True, ["Berlin"], True, False),
        ("Gurgaon", None, ["Delhi NCR"], False, True),
        ("Noida, Uttar Pradesh", False, ["NCR"], False, True),
        ("Pune, Maharashtra", None, ["India"], False, True),
        ("Mumbai", None, ["Remote"], False, False),  # "Remote" as a location means remote only
        ("Remote", None, ["Remote"], False, True),
        ("Anywhere in the world", None, [], False, True),  # no preference: everything
    ],
)
def test_location_matches(
    location: str | None, remote: bool | None, preferred: list[str], remote_ok: bool, expected: bool
) -> None:
    assert location_matches(location, remote, preferred, remote_ok) is expected
