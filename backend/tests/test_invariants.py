"""Invariant tests (PLAN.md §2). Never skip these. Later phases add the send-time checks."""

import uuid

import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import SecretDecryptionError, decrypt_secret, encrypt_secret
from app.models import Company, Contact, Job, Outreach, OutreachEvent, User
from app.models.enums import CampaignType, JobSourceType, OutreachEventType, OutreachStatus
from app.schemas.outreach import EmailDraft
from app.schemas.resume import Basics
from app.services.email.drafter import MAX_EDIT_WORDS, OPT_OUT_LINE, OPT_OUT_LINES, check_text, compose_body
from app.services.resume.files import save_tailored_pdf


async def _user_and_company(session: AsyncSession) -> tuple[User, Company]:
    user = User(email=f"{uuid.uuid4().hex[:8]}@example.com", name="Test")
    company = Company(name="Acme", domain=f"{uuid.uuid4().hex[:8]}.example.com")
    session.add_all([user, company])
    await session.flush()
    return user, company


# --- Invariant 4: one active outreach per (user, company), across both modes ---


async def test_second_active_outreach_to_same_company_is_rejected(session: AsyncSession) -> None:
    user, company = await _user_and_company(session)
    session.add(Outreach(user_id=user.id, company_id=company.id, campaign_type=CampaignType.OPEN))
    await session.flush()

    session.add(Outreach(user_id=user.id, company_id=company.id, campaign_type=CampaignType.OPEN))
    with pytest.raises(IntegrityError, match="uq_outreach_one_active_per_company"):
        await session.flush()


@pytest.mark.parametrize("finished", [OutreachStatus.CLOSED, OutreachStatus.SKIPPED, OutreachStatus.FAILED])
async def test_finished_outreach_does_not_block_a_new_one(
    session: AsyncSession, finished: OutreachStatus
) -> None:
    user, company = await _user_and_company(session)
    session.add(
        Outreach(user_id=user.id, company_id=company.id, campaign_type=CampaignType.OPEN, status=finished)
    )
    session.add(Outreach(user_id=user.id, company_id=company.id, campaign_type=CampaignType.OPEN))
    await session.flush()


async def test_job_and_open_outreach_share_the_one_active_limit(session: AsyncSession) -> None:
    user, company = await _user_and_company(session)
    job = Job(
        company_id=company.id, source=JobSourceType.MANUAL, title="Intern", dedupe_hash=uuid.uuid4().hex
    )
    session.add(job)
    await session.flush()
    session.add(
        Outreach(user_id=user.id, company_id=company.id, campaign_type=CampaignType.JOB, job_id=job.id)
    )
    await session.flush()
    session.add(Outreach(user_id=user.id, company_id=company.id, campaign_type=CampaignType.OPEN))
    with pytest.raises(IntegrityError, match="uq_outreach_one_active_per_company"):
        await session.flush()


async def test_different_users_may_each_contact_the_same_company(session: AsyncSession) -> None:
    user_a, company = await _user_and_company(session)
    user_b = User(email="b@example.com", name="B")
    session.add(user_b)
    await session.flush()
    session.add(Outreach(user_id=user_a.id, company_id=company.id, campaign_type=CampaignType.OPEN))
    session.add(Outreach(user_id=user_b.id, company_id=company.id, campaign_type=CampaignType.OPEN))
    await session.flush()


async def test_job_campaign_requires_job_id(session: AsyncSession) -> None:
    user, company = await _user_and_company(session)
    session.add(Outreach(user_id=user.id, company_id=company.id, campaign_type=CampaignType.JOB))
    with pytest.raises(IntegrityError, match="job_campaign_has_job"):
        await session.flush()


async def test_followup_count_capped_at_one(session: AsyncSession) -> None:
    user, company = await _user_and_company(session)
    session.add(
        Outreach(user_id=user.id, company_id=company.id, campaign_type=CampaignType.OPEN, followup_count=2)
    )
    with pytest.raises(IntegrityError, match="followup_count_max_one"):
        await session.flush()


# --- Invariant 6: secrets encrypted at rest ---


def test_secret_round_trip_and_ciphertext_hides_plaintext() -> None:
    ciphertext = encrypt_secret("1//refresh-token-value")
    assert "refresh-token-value" not in ciphertext
    assert decrypt_secret(ciphertext) == "1//refresh-token-value"


def test_secret_encrypted_with_other_key_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    ciphertext = encrypt_secret("api-key")
    monkeypatch.setattr(get_settings(), "fernet_key", Fernet.generate_key().decode())
    with pytest.raises(SecretDecryptionError):
        decrypt_secret(ciphertext)


# --- Invariant 5: users only see their own matches ---


async def test_user_cannot_see_or_change_another_users_matches(
    auth_client: AsyncClient, session: AsyncSession, other_user_headers: dict[str, str]
) -> None:
    from tests.test_matches_api import scored_user

    me = uuid.UUID((await auth_client.get("/auth/me")).json()["id"])
    await scored_user(session, me)
    mine = (await auth_client.get("/matches", params={"min_score": 0})).json()["items"]
    assert len(mine) == 2

    theirs = await auth_client.get("/matches", params={"min_score": 0}, headers=other_user_headers)
    assert theirs.status_code == 200
    assert theirs.json()["items"] == []
    for action in ("shortlist", "hide", "restore"):
        response = await auth_client.post(f"/matches/{mine[0]['id']}/{action}", headers=other_user_headers)
        assert response.status_code == 404, action
    # Blocking is per user: their block doesn't hide my matches.
    company_id = mine[0]["job"]["company"]["id"]
    assert (
        await auth_client.post(f"/companies/{company_id}/block", headers=other_user_headers)
    ).status_code == 200
    assert len((await auth_client.get("/matches", params={"min_score": 0})).json()["items"]) == 2


# --- Invariant 9: every outgoing email contains an opt-out line ---


def test_drafts_always_get_the_opt_out_line_and_edits_cannot_drop_it() -> None:
    draft = EmailDraft(
        subject="Referral", body="Would you refer me? Resume attached.", personalization_source="x"
    )
    body = compose_body(draft, Contact(full_name="Priya Nair", email="p@x.example"), Basics(name="A B"))
    [line] = [line for line in body.splitlines() if line in OPT_OUT_LINES]
    assert check_text("Referral", body, max_words=MAX_EDIT_WORDS) == []
    issues = check_text("Referral", body.replace(line, ""), max_words=MAX_EDIT_WORDS)
    assert [i.code for i in issues] == ["no_opt_out"]


# --- Invariant 11: no approval without an ATS-passing PDF; invariant 1: approval is recorded ---


async def test_approve_needs_a_passing_resume_and_records_who_approved(
    auth_client: AsyncClient, session: AsyncSession
) -> None:
    me = uuid.UUID((await auth_client.get("/auth/me")).json()["id"])
    company = Company(name="Acme", domain="acme.example")
    session.add(company)
    await session.flush()
    contact = Contact(
        company_id=company.id, full_name="Priya Nair", email="priya@acme.example", email_source="hunter"
    )
    session.add(contact)
    await session.flush()
    outreach = Outreach(
        user_id=me,
        company_id=company.id,
        campaign_type=CampaignType.OPEN,
        contact_id=contact.id,
        status=OutreachStatus.PENDING_REVIEW,
        subject="Referral",
        body=f"Hi Priya,\n\nCould you refer me? Resume attached.\n\n{OPT_OUT_LINE}\n\nBest,\nA B",
        tailored_resume={
            "ats": {"passed": False, "failures": ["cid"], "page_count": 1, "keyword_coverage": None}
        },
    )
    session.add(outreach)
    await session.commit()

    missing = await auth_client.post(f"/outreach/{outreach.id}/approve")
    assert missing.status_code == 409
    assert missing.json()["detail"]["code"] == "resume_missing"
    await save_tailored_pdf(me, str(outreach.id), "A_B_Resume.pdf", b"%PDF-1.7 fake")
    failing = await auth_client.post(f"/outreach/{outreach.id}/approve")
    assert failing.status_code == 409  # the PDF exists but failed the ATS check

    outreach.tailored_resume = {
        "ats": {"passed": True, "failures": [], "page_count": 1, "keyword_coverage": None}
    }
    await session.commit()
    ok = await auth_client.post(f"/outreach/{outreach.id}/approve")
    assert ok.status_code == 200, ok.text
    event = await session.scalar(
        select(OutreachEvent).where(OutreachEvent.type == OutreachEventType.APPROVED)
    )
    assert event is not None
    assert event.user_id == me
    assert event.payload["actor"] == str(me)
