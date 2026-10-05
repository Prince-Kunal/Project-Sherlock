"""Phase 5: selector rules (startup vs large, suppression, cooldown, invalid), role categories, the
finder's caching (zero provider calls within 60 days), lazy verification, HN hints, domain resolution,
the Hunter adapter's error mapping, and the outreach state machine."""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, Contact, Job, Outreach, OutreachEvent, SuppressionEntry, User
from app.models.enums import (
    CampaignType,
    EmailSource,
    JobSourceType,
    OutreachEventType,
    OutreachStatus,
    RoleCategory,
    SizeHint,
    SuppressionReason,
    VerificationStatus,
)
from app.services.contacts.base import ContactProviderAuthError, ContactQuotaError
from app.services.contacts.fake import FakeContactProvider
from app.services.contacts.finder import ContactFinder, NoContactError, size_from_headcount
from app.services.contacts.hunter import HunterProvider, map_status
from app.services.contacts.selector import Eligibility, categorize, is_startup, rank_contacts
from app.services.email.state import InvalidTransitionError, can_transition, transition
from tests.conftest import FIXTURES

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


# --- Role categories ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "department", "expected"),
    [
        ("Co-founder & CTO", None, RoleCategory.FOUNDER),
        ("Founder", None, RoleCategory.FOUNDER),
        ("Chief Executive Officer", None, RoleCategory.FOUNDER),
        ("Engineering Manager", None, RoleCategory.ENG_MANAGER),
        ("Head of Engineering", None, RoleCategory.ENG_MANAGER),
        ("Tech Lead, Payments", None, RoleCategory.ENG_MANAGER),
        ("Team Lead", "it", RoleCategory.ENG_MANAGER),
        ("Sales Manager", "sales", RoleCategory.OTHER),
        ("Technical Recruiter", None, RoleCategory.RECRUITER),
        ("Head of Talent Acquisition", None, RoleCategory.RECRUITER),
        ("People Partner", None, RoleCategory.RECRUITER),
        ("Senior Software Engineer", None, RoleCategory.ENGINEER),
        ("Account Executive", None, RoleCategory.OTHER),
        (None, None, RoleCategory.OTHER),
    ],
)
def test_categorize(title: str | None, department: str | None, expected: RoleCategory) -> None:
    assert categorize(title, None, department) == expected


# --- Selector ----------------------------------------------------------------------------------------


def person(
    email: str,
    title: str,
    *,
    department: str | None = None,
    seniority: str | None = None,
    status: VerificationStatus = VerificationStatus.VALID,
    last_contacted_days: int | None = None,
    confidence: int = 90,
) -> Contact:
    return Contact(
        email=email,
        full_name=email.split("@")[0].title(),
        title=title,
        department=department,
        seniority=seniority,
        role_category=categorize(title, seniority, department),
        verification_status=status,
        confidence=confidence,
        last_contacted_at=NOW - timedelta(days=last_contacted_days)
        if last_contacted_days is not None
        else None,
    )


PEOPLE = [
    person("ceo@x.io", "Founder & CEO"),
    person("cto@x.io", "Co-founder & CTO"),
    person("em@x.io", "Engineering Manager", department="it"),
    person("salesmgr@x.io", "Sales Manager", department="sales"),
    person("hr@x.io", "Technical Recruiter", department="hr"),
    person("sr@x.io", "Senior Software Engineer", department="it", seniority="senior"),
    person("jr@x.io", "Software Engineer", department="it", seniority="junior"),
]
OPEN = Eligibility(suppressed=frozenset(), now=NOW)


def emails(contacts: list[Contact]) -> list[str]:
    return [c.email for c in contacts]


def test_startup_prefers_founders_then_eng_manager_then_recruiter() -> None:
    ranked = rank_contacts(PEOPLE, startup=True, eligibility=OPEN)
    assert emails(ranked) == ["cto@x.io", "ceo@x.io", "em@x.io", "hr@x.io"]


def test_larger_company_prefers_eng_manager_then_recruiter_then_senior_engineer() -> None:
    ranked = rank_contacts(PEOPLE, startup=False, eligibility=OPEN)
    assert emails(ranked) == ["em@x.io", "hr@x.io", "sr@x.io"]  # no founders, juniors or sales


def test_suppressed_invalid_and_recently_contacted_are_skipped() -> None:
    people = [
        person("em@x.io", "Engineering Manager"),
        person("lead@x.io", "Tech Lead", status=VerificationStatus.INVALID),
        person("head@x.io", "Head of Engineering", last_contacted_days=29),  # in the 30-day cooldown
        person("vp@x.io", "VP Engineering", last_contacted_days=31),
    ]
    eligibility = Eligibility(suppressed=frozenset({"em@x.io"}), now=NOW)
    assert emails(rank_contacts(people, startup=False, eligibility=eligibility)) == ["vp@x.io"]


def test_ties_prefer_verified_addresses_then_confidence() -> None:
    people = [
        person("a@x.io", "Engineering Manager", status=VerificationStatus.ACCEPT_ALL),
        person("b@x.io", "Engineering Manager", status=VerificationStatus.VALID, confidence=60),
        person("c@x.io", "Engineering Manager", status=VerificationStatus.VALID, confidence=95),
    ]
    assert emails(rank_contacts(people, startup=False, eligibility=OPEN)) == ["c@x.io", "b@x.io", "a@x.io"]


def test_startup_by_size_hint_or_head_count() -> None:
    assert is_startup(Company(name="A", size_hint=SizeHint.STARTUP))
    assert not is_startup(Company(name="B", size_hint=SizeHint.LARGE))
    assert is_startup(Company(name="C", size_hint=SizeHint.MID, employee_count=40))  # ≤ 50 people
    assert not is_startup(Company(name="D", size_hint=SizeHint.STARTUP, employee_count=200))


@pytest.mark.parametrize(
    ("headcount", "expected"),
    [
        ("1-10", (SizeHint.STARTUP, 10)),
        ("11-50", (SizeHint.STARTUP, 50)),
        ("51-200", (SizeHint.MID, 200)),
        ("1001-5000", (SizeHint.LARGE, 5000)),
        ("10K+", (SizeHint.LARGE, 10000)),
        (None, (SizeHint.UNKNOWN, None)),
        ("lots", (SizeHint.UNKNOWN, None)),
    ],
)
def test_size_from_headcount(headcount: str | None, expected: tuple[SizeHint, int | None]) -> None:
    assert size_from_headcount(headcount) == expected


# --- Finder ------------------------------------------------------------------------------------------


async def _company(session: AsyncSession, **kwargs: object) -> Company:
    values: dict[str, object] = {
        "name": "Ledgerline",
        "domain": "ledgerline.example",
        "size_hint": SizeHint.STARTUP,
    }
    values.update(kwargs)
    company = Company(**values)
    session.add(company)
    await session.flush()
    return company


async def test_second_lookup_within_60_days_makes_no_provider_calls(session: AsyncSession) -> None:
    company = await _company(session)
    fake = FakeContactProvider()

    first = await ContactFinder(fake, now=NOW).find(session, company)
    assert first.email == "asha@ledgerline.example"  # the CTO at a startup
    assert [c[0] for c in fake.calls] == ["search_people"]  # verified in the search results already
    calls = len(fake.calls)

    second = await ContactFinder(fake, now=NOW + timedelta(days=59)).find(session, company)
    assert second.id == first.id
    assert len(fake.calls) == calls  # zero provider calls: cached contacts, fresh verification

    third = ContactFinder(fake, now=NOW + timedelta(days=61))
    await third.find(session, company)
    assert fake.calls[calls][0] == "search_people"  # the cache expired
    assert third.usage.searches == 1


async def test_unverified_candidates_are_verified_and_invalid_ones_skipped(session: AsyncSession) -> None:
    company = await _company(session, size_hint=SizeHint.LARGE)
    fake = FakeContactProvider(
        people=[
            ("Invalid", "Lead", "Engineering Manager", "it", "senior", None),  # verifies as invalid
            ("Catchall", "Recruiter", "Technical Recruiter", "hr", "senior", None),  # verifies as accept_all
        ]
    )
    finder = ContactFinder(fake, now=NOW)
    contact = await finder.find(session, company)
    assert contact.email == "catchall@ledgerline.example"
    assert contact.verification_status == VerificationStatus.ACCEPT_ALL
    assert [c[0] for c in fake.calls] == ["search_people", "verify", "verify"]
    assert finder.usage.verifications == 2
    manager = await session.scalar(select(Contact).where(Contact.email == "invalid@ledgerline.example"))
    assert manager is not None
    assert manager.verification_status == VerificationStatus.INVALID


async def test_nobody_suitable_raises_no_contact(session: AsyncSession) -> None:
    company = await _company(session, size_hint=SizeHint.LARGE)
    fake = FakeContactProvider(people=[("Sam", "Seller", "Account Executive", "sales", "senior", "valid")])
    with pytest.raises(NoContactError) as caught:
        await ContactFinder(fake, now=NOW).find(session, company)
    assert caught.value.reason == "no_contact"


async def test_suppression_and_cooldown_apply_to_found_contacts(session: AsyncSession) -> None:
    company = await _company(session)
    session.add(SuppressionEntry(email="asha@ledgerline.example", reason=SuppressionReason.OPT_OUT))
    await session.flush()
    fake = FakeContactProvider()
    contact = await ContactFinder(fake, now=NOW).find(session, company)
    assert contact.email == "vikram@ledgerline.example"  # the CTO opted out; next: eng manager

    contact.last_contacted_at = NOW - timedelta(days=3)  # another Sherlock user emailed him
    await session.flush()
    nxt = await ContactFinder(fake, now=NOW).find(session, company)
    assert nxt.email == "neha@ledgerline.example"


async def test_hn_contact_hints_are_tried_first(session: AsyncSession) -> None:
    company = await _company(session, domain=None)
    job = Job(
        company_id=company.id,
        source=JobSourceType.HN,
        title="Backend Engineer",
        dedupe_hash="h" * 64,
        source_meta={"contact_emails": ["jobs-invalid@acme.example", "hiring@acme.example"]},
    )
    fake = FakeContactProvider()
    contact = await ContactFinder(fake, now=NOW).find(session, company, job)
    assert contact.email == "hiring@acme.example"
    assert contact.email_source == EmailSource.HN
    assert [c[0] for c in fake.calls] == ["verify", "verify"]  # no people search needed


async def test_without_a_key_only_cached_contacts_are_used(session: AsyncSession) -> None:
    company = await _company(session)
    with pytest.raises(NoContactError) as caught:
        await ContactFinder(None, now=NOW).find(session, company)
    assert caught.value.reason == "contact_key_required"

    await ContactFinder(FakeContactProvider(), now=NOW).find(session, company)  # fills the cache
    contact = await ContactFinder(None, now=NOW + timedelta(days=10)).find(session, company)
    assert contact.email == "asha@ledgerline.example"


async def test_missing_domain_comes_from_the_job_url_or_a_name_search(session: AsyncSession) -> None:
    fake = FakeContactProvider(headcount="201-500")
    from_url = await _company(session, name="Acme Robotics", domain=None, size_hint=SizeHint.UNKNOWN)
    job = Job(
        company_id=from_url.id,
        source=JobSourceType.ADZUNA,
        title="Intern",
        url="https://careers.acmerobotics.example/jobs/42",
        dedupe_hash="a" * 64,
    )
    await ContactFinder(fake, now=NOW).find(session, from_url, job)
    assert fake.calls[0] == ("search_people", ("acmerobotics.example", ""))
    assert from_url.domain == "acmerobotics.example"
    assert (from_url.size_hint, from_url.employee_count) == (SizeHint.MID, 500)

    by_name = await _company(session, name="Bright Cart", domain=None, size_hint=SizeHint.UNKNOWN)
    await ContactFinder(fake, now=NOW).find(session, by_name)
    assert ("search_people", ("", "Bright Cart")) in fake.calls
    assert by_name.domain == "brightcart.example"


async def test_monthly_lookup_allowance(session: AsyncSession) -> None:
    company = await _company(session)
    with pytest.raises(NoContactError) as caught:
        await ContactFinder(FakeContactProvider(), now=NOW, searches_left=0).find(session, company)
    assert caught.value.reason == "contact_lookup_limit"


@pytest.mark.parametrize(
    ("error", "reason"),
    [(ContactQuotaError("x"), "contact_quota"), (ContactProviderAuthError("x"), "contact_key_invalid")],
)
async def test_provider_errors_become_reasons(session: AsyncSession, error: Exception, reason: str) -> None:
    class Failing(FakeContactProvider):
        async def search_people(self, *, domain: str | None = None, company: str | None = None) -> object:  # type: ignore[override]
            raise error

    company = await _company(session)
    with pytest.raises(NoContactError) as caught:
        await ContactFinder(Failing(), now=NOW).find(session, company)
    assert caught.value.reason == reason


# --- Hunter adapter ----------------------------------------------------------------------------------


@respx.mock
async def test_hunter_restricted_account_is_an_auth_error_and_key_stays_out_of_the_url() -> None:
    body = json.loads((FIXTURES / "sources" / "hunter" / "error_restricted.json").read_text())
    route = respx.get("https://api.hunter.io/v2/account").mock(return_value=httpx.Response(429, json=body))
    with pytest.raises(ContactProviderAuthError, match="restricted"):
        await HunterProvider("secret-key").check_key()
    request = route.calls.last.request
    assert request.headers["X-API-KEY"] == "secret-key"
    assert "secret-key" not in str(request.url)


@respx.mock
async def test_hunter_quota_error() -> None:
    respx.get("https://api.hunter.io/v2/email-verifier").mock(
        return_value=httpx.Response(429, json={"errors": [{"id": "usage_exceeded", "details": "No credits"}]})
    )
    with pytest.raises(ContactQuotaError):
        await HunterProvider("k").verify("a@b.co")


@pytest.mark.parametrize(
    ("status", "result", "expected"),
    [
        ("valid", None, VerificationStatus.VALID),
        ("accept_all", None, VerificationStatus.ACCEPT_ALL),
        ("invalid", None, VerificationStatus.INVALID),
        ("disposable", None, VerificationStatus.INVALID),
        ("unknown", None, VerificationStatus.UNKNOWN),
        ("webmail", "deliverable", VerificationStatus.VALID),
        ("webmail", "risky", VerificationStatus.ACCEPT_ALL),
        ("webmail", "undeliverable", VerificationStatus.INVALID),
    ],
)
def test_hunter_status_mapping(status: str, result: str | None, expected: VerificationStatus) -> None:
    assert map_status(status, result) == expected


# --- State machine -----------------------------------------------------------------------------------


async def test_transitions_are_validated_and_recorded(session: AsyncSession) -> None:
    user = User(email="s@example.com", name="S")
    company = await _company(session)
    session.add(user)
    await session.flush()
    outreach = Outreach(user_id=user.id, company_id=company.id, campaign_type=CampaignType.OPEN)
    session.add(outreach)
    await session.flush()

    with pytest.raises(ValueError, match="failure_reason"):
        await transition(session, outreach, OutreachStatus.FAILED, actor_id=None)
    await transition(session, outreach, OutreachStatus.FAILED, actor_id=None, failure_reason="no_contact")
    assert (outreach.status, outreach.failure_reason) == (OutreachStatus.FAILED, "no_contact")
    with pytest.raises(InvalidTransitionError):
        await transition(session, outreach, OutreachStatus.APPROVED, actor_id=user.id)
    await transition(session, outreach, OutreachStatus.DRAFTING, actor_id=user.id)
    assert outreach.failure_reason is None

    events = (await session.scalars(select(OutreachEvent).order_by(OutreachEvent.created_at))).all()
    assert [e.type for e in events] == [OutreachEventType.FAILED, OutreachEventType.RETRIED]
    assert events[0].payload == {
        "from": "drafting",
        "to": "failed",
        "actor": "system",
        "reason": "no_contact",
    }
    assert events[1].payload["actor"] == str(user.id)


def test_state_machine_matches_the_plan() -> None:
    s = OutreachStatus
    for current, target in [
        (s.DRAFTING, s.PENDING_REVIEW),
        (s.PENDING_REVIEW, s.APPROVED),
        (s.PENDING_REVIEW, s.SKIPPED),
        (s.APPROVED, s.SCHEDULED),
        (s.SCHEDULED, s.SENT),
        (s.SCHEDULED, s.SEND_FAILED),
        (s.SEND_FAILED, s.PENDING_REVIEW),
        (s.SENT, s.REPLIED),
        (s.SENT, s.FOLLOWUP_DUE),
        (s.FOLLOWUP_DUE, s.PENDING_REVIEW),
        (s.REPLIED, s.CLOSED),
        (s.DRAFTING, s.FAILED),
    ]:
        assert can_transition(current, target), (current, target)
    for current, target in [
        (s.DRAFTING, s.APPROVED),  # never approved without review
        (s.DRAFTING, s.SENT),
        (s.PENDING_REVIEW, s.SENT),  # never sent without approval (invariant 1)
        (s.APPROVED, s.SENT),
        (s.SKIPPED, s.PENDING_REVIEW),
        (s.CLOSED, s.DRAFTING),
    ]:
        assert not can_transition(current, target), (current, target)
