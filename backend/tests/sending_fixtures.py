"""Helpers for the Phase 7 sending and reply tests: a user, ready-to-send outreach, a fake mailbox."""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, Contact, Outreach, User, UserPreferences
from app.models.enums import (
    CampaignType,
    EmailSource,
    OutreachEventType,
    OutreachStatus,
    RoleCategory,
    VerificationStatus,
)
from app.services.email.connection import GmailFactory
from app.services.email.drafter import OPT_OUT_LINE
from app.services.email.fake_gmail import FakeGmailClient
from app.services.email.gmail import GmailClient
from app.services.email.state import record_event, transition
from app.services.resume.files import save_tailored_pdf

# Monday 12 Oct 2026, 11:00 in Kolkata: inside the default 09:30-18:00 send window.
MONDAY_11_IST = datetime(2026, 10, 12, 5, 30, tzinfo=UTC)
PDF = b"%PDF-1.7 tailored resume"


async def sender(session: AsyncSession, email: str = "rohan@example.com", **prefs: object) -> User:
    user = User(email=email, name="Rohan Das", timezone="Asia/Kolkata")
    session.add(user)
    await session.flush()
    session.add(UserPreferences(user_id=user.id, **prefs))
    await session.commit()
    return user


async def sendable(
    session: AsyncSession,
    user: User,
    *,
    email: str | None = None,
    approve: bool = True,
    company: str | None = None,
) -> Outreach:
    """An outreach in review (drafted, with an ATS-passing PDF), approved by its owner unless
    `approve=False`."""
    tag = uuid.uuid4().hex[:6]
    row = Company(name=company or f"Company {tag}", domain=f"{tag}.example")
    session.add(row)
    await session.flush()
    contact = Contact(
        company_id=row.id,
        full_name="Priya Nair",
        title="Engineering Manager",
        email=email or f"priya@{tag}.example",
        email_source=EmailSource.HUNTER,
        verification_status=VerificationStatus.VALID,
        role_category=RoleCategory.ENG_MANAGER,
    )
    session.add(contact)
    await session.flush()
    outreach = Outreach(
        user_id=user.id,
        company_id=row.id,
        campaign_type=CampaignType.OPEN,
        contact_id=contact.id,
        status=OutreachStatus.PENDING_REVIEW,
        # Open outreach (no job row needed), so the text never claims an opening (invariant 10).
        subject=f"Backend interns at {row.name}?",
        body=f"Hi Priya,\n\nDoes your team take backend interns? Resume's attached.\n\n{OPT_OUT_LINE}"
        "\n\nThanks,\nRohan Das",
        tailored_resume={"ats": {"passed": True, "failures": [], "page_count": 1, "keyword_coverage": None}},
    )
    session.add(outreach)
    await session.flush()
    await record_event(session, outreach, OutreachEventType.DRAFTED, {"actor": "system"})
    await save_tailored_pdf(user.id, str(outreach.id), "Rohan_Das_Resume.pdf", PDF)
    if approve:
        await transition(session, outreach, OutreachStatus.APPROVED, actor_id=user.id)
    await session.commit()
    return outreach


def mailbox_factory(mailbox: GmailClient) -> GmailFactory:
    async def factory(_session: AsyncSession, _user: User) -> GmailClient:
        return mailbox

    return factory


def fake_mailbox(user: User) -> FakeGmailClient:
    return FakeGmailClient(user.email)
