"""Invariant tests (PLAN.md §2). Never skip these. Later phases add the send-time checks."""

import uuid

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import SecretDecryptionError, decrypt_secret, encrypt_secret
from app.models import Company, Job, Outreach, User
from app.models.enums import CampaignType, JobSourceType, OutreachStatus


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
