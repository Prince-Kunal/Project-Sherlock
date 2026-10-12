"""Phase 6: the draft validator, the drafter's retry, the daily pipeline (match → contact → tailor →
draft → pending_review) end to end on fakes, and the review API (edit, regenerate, approve, skip)."""

import re
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis
from app.models import (
    Company,
    Contact,
    Job,
    JobMatch,
    Outreach,
    OutreachEvent,
    UsageLedger,
    User,
    UserPreferences,
)
from app.models.enums import OutreachEventType, OutreachStatus, RoleCategory
from app.schemas.outreach import EmailDraft
from app.schemas.resume import Basics, Link
from app.services.contacts.fake import FakeContactProvider
from app.services.email.drafter import (
    OPT_OUT_LINES,
    Drafter,
    DraftError,
    DraftInputs,
    check_text,
    compose_body,
    key_sentences,
    opt_out_line,
    replace_greeting,
    validate_draft,
)
from app.services.email.pipeline import DraftPipeline, users_due_for_drafts
from app.services.llm.client import LLMQuotaExhaustedError
from app.services.llm.fake import FakeLLMClient
from app.services.registry import build_fake_llm_client
from app.services.resume.skills import get_lexicon
from tests.conftest import recorded
from tests.test_matches_api import _me, scored_user

CONTEXT = [
    "Build and maintain REST APIs in Python (Django) backed by PostgreSQL.",
    "Containerise services with Docker and help improve our CI pipeline.",
]
BASICS = Basics(
    name="Rohan Das",
    email="rohan@example.com",
    links=[
        Link(label="GitHub", url="https://github.com/rohandas"),
        Link(label="LinkedIn", url="https://www.linkedin.com/in/rohandas/"),
    ],
)


def _contact(name: str = "Priya Nair", email: str = "priya@ledgerline.example") -> Contact:
    return Contact(
        full_name=name, email=email, role_category=RoleCategory.ENG_MANAGER, title="Engineering Manager"
    )


def _draft(**overrides: Any) -> EmailDraft:
    data: dict[str, Any] = {
        "subject": "Backend intern role at Ledgerline",
        "body": (
            "I saw the Backend Engineering Intern role and the focus on Python APIs over PostgreSQL is "
            "close to what I've built. I built a Django REST backend on PostgreSQL for a college project.\n\n"
            "Would you be open to referring me, or pointing me to the right person? My resume is attached."
        ),
        "personalization_source": CONTEXT[0],
    }
    return EmailDraft(**{**data, **overrides})


def _without_opt_out(body: str) -> str:
    return "\n".join(line for line in body.splitlines() if line not in OPT_OUT_LINES)


def _issues(draft: EmailDraft) -> set[str]:
    return {i.code for i in validate_draft(draft, CONTEXT, compose_body(draft, _contact(), BASICS))}


# --- Validator ---------------------------------------------------------------------------------------


def test_a_good_draft_passes_and_is_composed_with_greeting_opt_out_and_signature() -> None:
    draft = _draft()
    assert _issues(draft) == set()
    body = compose_body(draft, _contact(), BASICS)
    assert body.startswith("Hi Priya,\n\n")
    assert opt_out_line(_contact()) in body
    assert re.search(
        r"\n\n(Thanks|Best|Cheers),\nRohan Das\ngithub.com/rohandas \| linkedin.com/in/rohandas$", body
    )


def test_opt_out_line_and_sign_off_vary_by_contact_but_are_stable() -> None:
    contacts = [_contact(email=f"person{i}@ledgerline.example") for i in range(12)]
    bodies = [compose_body(_draft(), c, BASICS) for c in contacts]
    assert len({opt_out_line(c) for c in contacts}) > 1
    assert all(opt_out_line(c) in b for c, b in zip(contacts, bodies, strict=True))
    assert compose_body(_draft(), contacts[0], BASICS) == bodies[0]  # same contact, same email
    assert all(check_text("s", b, max_words=150) == [] for b in bodies)  # every variant is an opt-out


def test_missing_opt_out_is_rejected() -> None:
    assert {
        i.code for i in check_text("Subject", "Hi,\n\nPlease refer me. Resume attached.", max_words=150)
    } == {"no_opt_out"}


def test_too_long_is_rejected() -> None:
    long_body = " ".join(["word"] * 140) + ". My resume is attached."
    assert "too_long" in _issues(_draft(body=long_body))


def test_a_personalization_source_not_in_the_context_is_rejected() -> None:
    assert "unknown_source" in _issues(_draft(personalization_source="We are a fast-growing unicorn."))
    # Curly quotes, case and spacing don't matter; a fragment of a real sentence is fine.
    assert _issues(_draft(personalization_source="build and maintain  REST APIs in Python")) == set()


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"subject": "x" * 71}, "subject_too_long"),
        ({"subject": "  "}, "subject_empty"),
        ({"body": "Hi [Name], please refer me at [Company]. Resume attached."}, "placeholder"),
        ({"body": "Would you refer me for the backend role?"}, "no_attachment_mention"),
        ({"body": "Hi Priya,\n\nWould you refer me? My resume is attached."}, "greeting_or_signoff"),
        ({"body": "Would you refer me? My resume is attached.\n\nBest,\nRohan"}, "greeting_or_signoff"),
    ],
)
def test_other_rules(overrides: dict[str, Any], code: str) -> None:
    assert code in _issues(_draft(**overrides))


def test_greeting_falls_back_when_the_name_is_just_the_address() -> None:
    body = compose_body(_draft(), _contact(name="priya", email="priya@ledgerline.example"), BASICS)
    assert body.startswith("Hi there,")
    assert replace_greeting(body, _contact(name="Vikram Iyer")).startswith("Hi Vikram,\n")


def test_key_sentences_prefer_the_candidates_skills_and_keep_jd_order() -> None:
    jd = (
        "About Ledgerline\nWe build reconciliation software for Indian fintechs.\n\nWhat you'll do\n"
        "- Build and maintain REST APIs in Python (Django) backed by PostgreSQL.\n"
        "- Write tests and ship features with code review from senior engineers.\n"
        "- Containerise services with Docker and help improve our CI pipeline.\n"
        "Email jobs@ledgerline.example to apply."
    )
    lexicon = get_lexicon()
    chosen = key_sentences(jd, {"python", "postgresql", "docker"}, lexicon, limit=2)
    assert chosen == [
        "Build and maintain REST APIs in Python (Django) backed by PostgreSQL.",
        "Containerise services with Docker and help improve our CI pipeline.",
    ]
    assert all("@" not in s for s in key_sentences(jd, set(), lexicon, limit=10))  # PII redacted


# --- Drafter retry -----------------------------------------------------------------------------------


def _inputs() -> DraftInputs:
    job = Job(title="Backend Engineering Intern", location="Bengaluru", description_text="\n".join(CONTEXT))
    return DraftInputs(
        job=job,
        company=Company(name="Ledgerline"),
        contact=_contact(),
        basics=BASICS,
        about_me="Final-year CS student who likes backend work.",
        highlights=["Built a Django REST backend on PostgreSQL"],
        skills={"python", "postgresql", "docker"},
        hint="mention I can start in May",
    )


async def test_drafter_retries_once_with_the_issues_then_succeeds() -> None:
    bad = _draft(personalization_source="Something the JD never said at all.").model_dump()
    llm = FakeLLMClient(responses={"draft_email": [bad, _draft().model_dump()]})
    result = await Drafter(llm).draft(_inputs(), None)
    assert result.subject == "Backend intern role at Ledgerline"
    assert result.body.startswith("Hi Priya,")
    prompts = [p for r, p in llm.calls if r.prompt_name == "draft_email"]
    assert len(prompts) == 2
    assert "[unknown_source]" in prompts[1]
    assert "mention I can start in May" in prompts[0]
    assert "rohan@example.com" not in prompts[0]  # §3.1: no personal details in prompts
    assert "Rohan Das" not in prompts[0]


async def test_drafter_gives_up_after_two_invalid_drafts() -> None:
    llm = FakeLLMClient(responses={"draft_email": _draft(body="Refer me please.").model_dump()})
    with pytest.raises(DraftError) as caught:
        await Drafter(llm).draft(_inputs(), None)
    assert caught.value.reason == "draft_validation_failed"


async def test_a_recorded_real_draft_passes_the_validator() -> None:
    """A real smart-model answer to draft_email v1 (tests/fixtures/record_llm.py draft)."""
    from tests.fixtures.record_llm import draft_inputs

    llm = FakeLLMClient(responses={"draft_email": recorded("draft_email", "rohan_ledgerline")})
    result = await Drafter(llm).draft(draft_inputs(), None)
    assert len(llm.calls) == 1  # accepted first time
    assert result.body.startswith("Hi Priya,\n\n")
    assert result.personalization_source in Drafter(llm).contexts(draft_inputs())
    assert result.body.rstrip().endswith("rohandas.example.dev")


# --- Pipeline end to end (acceptance criterion) -----------------------------------------------------


async def _two_candidates(session: AsyncSession, user_id: uuid.UUID, batch: int) -> dict[str, uuid.UUID]:
    """The scored fixture user with two strong matches at different companies: Ledgerline's intern job
    and Brightcart's (forced to 90). Ferrovia's is forced to 90 too, but scoring found it full-time,
    so this internship seeker's hard filters drop it."""
    ids = await scored_user(session, user_id)
    for key in ("unknown_type", "irrelevant"):
        await session.execute(update(JobMatch).where(JobMatch.job_id == ids[key]).values(llm_score=90))
    await session.execute(
        update(UserPreferences).where(UserPreferences.user_id == user_id).values(daily_draft_batch=batch)
    )
    await session.commit()
    return ids


def _pipeline(llm: FakeLLMClient, contacts: FakeContactProvider) -> DraftPipeline:
    return DraftPipeline(llm, lambda _key: contacts)


async def test_build_daily_drafts_end_to_end_then_approve(
    with_hunter_key: AsyncClient, session: AsyncSession, fake_contacts: FakeContactProvider
) -> None:
    user_id = await _me(with_hunter_key)
    await _two_candidates(session, user_id, batch=2)
    llm = build_fake_llm_client()

    summary = await _pipeline(llm, fake_contacts).build_for_user(session, user_id)
    assert (summary.drafted, summary.failed, summary.stopped) == (2, 0, None)
    pending = (await with_hunter_key.get("/outreach", params={"status": "pending_review"})).json()
    assert pending["total"] == 2  # N ≤ batch size
    assert {i["company"]["name"] for i in pending["items"]} == {"Ledgerline", "Brightcart"}

    # Running again doesn't add drafts: the queue is full.
    again = await _pipeline(llm, fake_contacts).build_for_user(session, user_id)
    assert again.drafted == 0

    draft = (await with_hunter_key.get(f"/outreach/{pending['items'][0]['id']}")).json()
    assert draft["status"] == "pending_review"
    assert draft["body"].startswith("Hi Asha,")
    assert set(draft["body"].splitlines()) & set(OPT_OUT_LINES)
    assert draft["style_warnings"] == []
    assert draft["ats"]["passed"] is True
    assert draft["resume_filename"] == "Rohan_Das_Resume.pdf"
    assert draft["contact"]["full_name"] == "Asha Rao"
    pdf = await with_hunter_key.get(draft["resume_pdf_url"])
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")

    approved = await with_hunter_key.post(f"/outreach/{draft['id']}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert approved.json()["approved_at"] is not None
    events = (
        await session.scalars(
            select(OutreachEvent)
            .where(OutreachEvent.outreach_id == uuid.UUID(draft["id"]))
            .order_by(OutreachEvent.created_at)
        )
    ).all()
    assert [e.type for e in events] == [
        OutreachEventType.CONTACT_CHANGED,
        OutreachEventType.DRAFTED,
        OutreachEventType.APPROVED,
    ]
    assert events[-1].payload["actor"] == str(user_id)

    ledger = {
        (row.operation, row.units)
        for row in (await session.scalars(select(UsageLedger).where(UsageLedger.user_id == user_id))).all()
    }
    assert ("tailor_resume", 1) in ledger
    assert ("draft_email", 1) in ledger


async def test_a_failing_draft_fails_that_job_and_the_batch_goes_on(
    with_hunter_key: AsyncClient, session: AsyncSession, fake_contacts: FakeContactProvider
) -> None:
    user_id = await _me(with_hunter_key)
    await _two_candidates(session, user_id, batch=3)
    llm = build_fake_llm_client()
    good = llm._responders["draft_email"]
    seen: list[str] = []

    def first_one_fails(prompt: str) -> Any:
        seen.append(prompt)
        draft = good(prompt)
        return {**draft, "personalization_source": "Invented."} if len(seen) <= 2 else draft

    llm.add_responder("draft_email", first_one_fails)
    summary = await _pipeline(llm, fake_contacts).build_for_user(session, user_id)
    assert (summary.drafted, summary.failed) == (1, 1)
    failed = await session.scalar(select(Outreach).where(Outreach.status == OutreachStatus.FAILED))
    assert failed is not None
    assert failed.failure_reason == "draft_validation_failed"

    # Retry from the review queue drafts it (the fake now answers well).
    retried = await with_hunter_key.post(f"/outreach/{failed.id}/retry")
    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "pending_review"


async def test_quota_exhaustion_pauses_and_the_next_run_resumes(
    with_hunter_key: AsyncClient, session: AsyncSession, fake_contacts: FakeContactProvider
) -> None:
    user_id = await _me(with_hunter_key)
    await _two_candidates(session, user_id, batch=1)
    llm = build_fake_llm_client()
    good = llm._responders["draft_email"]

    def exhausted(prompt: str) -> Any:
        raise LLMQuotaExhaustedError("daily quota")

    llm.add_responder("draft_email", exhausted)
    summary = await _pipeline(llm, fake_contacts).build_for_user(session, user_id)
    assert summary.stopped == "LLMQuotaExhaustedError"
    outreach = await session.scalar(select(Outreach).where(Outreach.user_id == user_id))
    assert outreach is not None
    assert outreach.status == OutreachStatus.DRAFTING  # not failed: nothing was wrong with the job
    assert outreach.contact_id is not None
    assert outreach.tailored_resume is not None

    llm.add_responder("draft_email", good)
    searches = sum(1 for name, _ in fake_contacts.calls if name == "search_people")
    tailors = sum(1 for r, _ in llm.calls if r.prompt_name == "tailor")
    resumed = await _pipeline(llm, fake_contacts).build_for_user(session, user_id)
    assert resumed.drafted == 1
    await session.refresh(outreach)
    assert outreach.status == OutreachStatus.PENDING_REVIEW
    # Neither the contact search nor the tailoring was repeated.
    assert sum(1 for name, _ in fake_contacts.calls if name == "search_people") == searches
    assert sum(1 for r, _ in llm.calls if r.prompt_name == "tailor") == tailors


async def test_paused_users_and_users_without_a_key_get_no_drafts(session: AsyncSession) -> None:
    from tests.matching_fixtures import seed_matching_user

    no_key = await seed_matching_user(session, email="nokey@example.com", with_key=False)
    pipeline = _pipeline(build_fake_llm_client(), FakeContactProvider())
    assert (await pipeline.build_for_user(session, no_key.id)).stopped == "no_llm_key"
    paused = await seed_matching_user(session, email="paused@example.com")
    await session.execute(
        update(UserPreferences).where(UserPreferences.user_id == paused.id).values(paused=True)
    )
    await session.commit()
    assert (await pipeline.build_for_user(session, paused.id)).stopped == "paused"


async def test_users_are_due_at_seven_local_time_once_a_day(session: AsyncSession) -> None:
    kolkata = User(email="in@example.com", name="In", timezone="Asia/Kolkata")
    berlin = User(email="de@example.com", name="De", timezone="Europe/Berlin")
    session.add_all([kolkata, berlin])
    await session.commit()
    seven_in_india = datetime(2026, 10, 12, 1, 30, tzinfo=UTC)  # 07:00 IST, 03:30 in Berlin
    assert await users_due_for_drafts(session, get_redis(), seven_in_india) == [kolkata.id]
    assert await users_due_for_drafts(session, get_redis(), seven_in_india) == []  # already ran today
    seven_in_berlin = datetime(2026, 10, 12, 5, 10, tzinfo=UTC)  # 07:10 CEST
    assert await users_due_for_drafts(session, get_redis(), seven_in_berlin) == [berlin.id]


# --- Review API ----------------------------------------------------------------------------------------


@pytest.fixture
async def drafted(
    with_hunter_key: AsyncClient, session: AsyncSession, fake_contacts: FakeContactProvider
) -> AsyncIterator[dict[str, Any]]:
    """One draft in review, made through the "Draft now" button."""
    from app.main import app
    from app.services.registry import get_llm_client

    await scored_user(session, await _me(with_hunter_key))
    llm = build_fake_llm_client()
    app.dependency_overrides[get_llm_client] = lambda: llm
    [match] = (await with_hunter_key.get("/matches")).json()["items"]
    response = await with_hunter_key.post(f"/matches/{match['id']}/draft")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    assert body["status"] == "pending_review"
    assert body["match_id"] == match["id"]
    yield body
    app.dependency_overrides.pop(get_llm_client, None)


async def test_edit_keeps_the_original_in_the_event(
    with_hunter_key: AsyncClient, session: AsyncSession, drafted: dict[str, Any]
) -> None:
    new_body = drafted["body"].replace("Would you be open", "Would you possibly be open")
    response = await with_hunter_key.patch(
        f"/outreach/{drafted['id']}", json={"subject": "Backend intern at Ledgerline", "body": new_body}
    )
    assert response.status_code == 200, response.text
    assert response.json()["subject"] == "Backend intern at Ledgerline"
    assert response.json()["body"] == new_body
    event = await session.scalar(select(OutreachEvent).where(OutreachEvent.type == OutreachEventType.EDITED))
    assert event is not None
    assert event.payload["before"] == {"subject": drafted["subject"], "body": drafted["body"]}
    assert event.payload["after"]["body"] == new_body

    # Removing the opt-out line is refused (invariant 9), and so are placeholders.
    no_opt_out = await with_hunter_key.patch(
        f"/outreach/{drafted['id']}", json={"body": _without_opt_out(new_body)}
    )
    assert no_opt_out.status_code == 422
    assert no_opt_out.json()["detail"]["code"] == "draft_invalid"
    placeholder = await with_hunter_key.patch(f"/outreach/{drafted['id']}", json={"subject": "Hi [Name]"})
    assert placeholder.status_code == 422


async def test_regenerate_with_a_hint(
    with_hunter_key: AsyncClient, session: AsyncSession, drafted: dict[str, Any]
) -> None:
    from app.main import app
    from app.services.registry import get_llm_client

    llm: FakeLLMClient = app.dependency_overrides[get_llm_client]()  # type: ignore[assignment]
    response = await with_hunter_key.post(
        f"/outreach/{drafted['id']}/regenerate", json={"hint": "mention I can start in May"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "pending_review"
    _, prompt = [c for c in llm.calls if c[0].prompt_name == "draft_email"][-1]
    assert "mention I can start in May" in prompt
    event = await session.scalar(
        select(OutreachEvent).where(OutreachEvent.type == OutreachEventType.REGENERATED)
    )
    assert event is not None
    assert event.payload["before"]["body"] == drafted["body"]
    assert event.payload["hint"] == "mention I can start in May"


async def test_skip_and_locked_drafts(with_hunter_key: AsyncClient, drafted: dict[str, Any]) -> None:
    skipped = await with_hunter_key.post(f"/outreach/{drafted['id']}/skip")
    assert skipped.json()["status"] == "skipped"
    for method, path, body in [
        ("POST", "approve", None),
        ("POST", "skip", None),
        ("PATCH", "", {"subject": "x"}),
        ("POST", "regenerate", {}),
    ]:
        url = f"/outreach/{drafted['id']}" + (f"/{path}" if path else "")
        response = await with_hunter_key.request(method, url, json=body)
        assert response.status_code == 409, (path, response.text)
        assert response.json()["detail"]["code"] == "draft_locked"


async def test_swapping_the_contact_greets_the_new_person(
    with_hunter_key: AsyncClient, drafted: dict[str, Any]
) -> None:
    response = await with_hunter_key.post(
        f"/outreach/{drafted['id']}/contact",
        json={
            "email": "meera@ledgerline.example",
            "full_name": "Meera Joshi",
            "title": "Engineering Manager",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["body"].startswith("Hi Meera,\n")


async def test_list_and_stats(with_hunter_key: AsyncClient, drafted: dict[str, Any]) -> None:
    listed = (await with_hunter_key.get("/outreach", params={"status": "pending_review"})).json()
    assert [i["id"] for i in listed["items"]] == [drafted["id"]]
    assert listed["items"][0]["job_title"] == "Backend Engineering Intern"
    assert listed["items"][0]["fit_score"] == drafted["fit_score"]
    assert (await with_hunter_key.get("/outreach", params={"status": "approved"})).json()["total"] == 0
    stats = (await with_hunter_key.get("/outreach/stats")).json()
    assert stats == {
        "pending_review": 1,
        "new_matches": 0,  # the only match is in the pipeline now
        "sent_this_week": 0,
        "daily_send_cap": 15,
        "replies": 0,
        "followups_due": 0,
        "failed": 0,
        "new_company_matches": 0,
        "by_mode": {"job": {"sent": 0, "replied": 0}, "open": {"sent": 0, "replied": 0}},
    }


async def test_other_users_cannot_touch_a_draft(
    with_hunter_key: AsyncClient, drafted: dict[str, Any], other_user_headers: dict[str, str]
) -> None:
    oid = drafted["id"]
    for method, path, body in [
        ("GET", "", None),
        ("PATCH", "", {"subject": "mine now"}),
        ("POST", "/approve", None),
        ("POST", "/skip", None),
        ("POST", "/regenerate", {}),
        ("POST", "/retry", None),
        ("GET", "/resume.pdf", None),
    ]:
        response = await with_hunter_key.request(
            method, f"/outreach/{oid}{path}", json=body, headers=other_user_headers
        )
        assert response.status_code == 404, (path, response.status_code)
    others = await with_hunter_key.get("/outreach", headers=other_user_headers)
    assert others.json()["total"] == 0
    assert (await with_hunter_key.get(f"/outreach/{oid}")).json()["status"] == "pending_review"


async def test_review_routes_require_auth(client: AsyncClient) -> None:
    some = uuid.uuid4()
    for method, path in [
        ("GET", "/outreach"),
        ("GET", "/outreach/stats"),
        ("POST", "/outreach/build"),
        ("PATCH", f"/outreach/{some}"),
        ("POST", f"/outreach/{some}/approve"),
        ("POST", f"/outreach/{some}/regenerate"),
        ("GET", f"/outreach/{some}/resume.pdf"),
        ("POST", f"/matches/{some}/draft"),
    ]:
        assert (await client.request(method, path)).status_code == 401, path
