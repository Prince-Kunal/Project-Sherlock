"""Phase 5 API: finding a contact for a match starts its outreach; no contact → failed/no_contact and a
contact can be added by hand (verified); Hunter key settings; isolation between users."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Contact, JobMatch, OutreachEvent, SuppressionEntry, UsageLedger
from app.models.enums import JobMatchStatus, OutreachEventType, SuppressionReason
from app.services.contacts.fake import FakeContactProvider
from tests.test_matches_api import _me, scored_user


async def _top_match(client: AsyncClient) -> dict[str, Any]:
    [item] = (await client.get("/matches")).json()["items"]
    return item


async def test_find_contact_starts_the_outreach_with_the_best_person(
    with_hunter_key: AsyncClient, session: AsyncSession, fake_contacts: FakeContactProvider
) -> None:
    await scored_user(session, await _me(with_hunter_key))
    match = await _top_match(with_hunter_key)

    response = await with_hunter_key.post(f"/matches/{match['id']}/find-contact")
    assert response.status_code == 200, response.text
    outreach = response.json()
    assert outreach["status"] == "drafting"
    assert outreach["company"]["name"] == "Ledgerline"
    contact = outreach["contact"]
    # Ledgerline's size is unknown until Hunter reports "11-50" people: a startup, so the CTO.
    assert (contact["full_name"], contact["role_category"]) == ("Asha Rao", "founder")
    assert contact["verification_status"] == "valid"

    # The match is now in the pipeline and shows its outreach.
    listed = await _top_match(with_hunter_key)
    assert listed["status"] == "in_pipeline"
    assert listed["outreach"]["id"] == outreach["id"]

    # Doing it again reuses the outreach and the cached contact: no more Hunter calls.
    calls = len(fake_contacts.calls)
    again = (await with_hunter_key.post(f"/matches/{match['id']}/find-contact")).json()
    assert again["id"] == outreach["id"]
    assert len(fake_contacts.calls) == calls

    ledger = (await session.scalars(select(UsageLedger).where(UsageLedger.provider == "hunter"))).all()
    assert [(row.operation, row.units) for row in ledger] == [("hunter_search", 1)]
    events = (await session.scalars(select(OutreachEvent))).all()
    assert [e.type for e in events] == [OutreachEventType.CONTACT_CHANGED]


async def test_no_contact_fails_the_outreach_and_a_manual_contact_revives_it(
    with_hunter_key: AsyncClient, session: AsyncSession, fake_contacts: FakeContactProvider
) -> None:
    await scored_user(session, await _me(with_hunter_key))
    fake_contacts.people = [("Sam", "Seller", "Account Executive", "sales", "senior", "valid")]
    match = await _top_match(with_hunter_key)

    failed = (await with_hunter_key.post(f"/matches/{match['id']}/find-contact")).json()
    assert failed["status"] == "failed"
    assert failed["failure_reason"] == "no_contact"
    assert "Ledgerline" in failed["failure_message"]
    assert failed["contact"] is None

    # Undeliverable or suppressed addresses are refused.
    bad = await with_hunter_key.post(
        f"/outreach/{failed['id']}/contact", json={"email": "bounce@ledgerline.example"}
    )
    assert bad.status_code == 422
    assert bad.json()["detail"]["code"] == "email_not_deliverable"
    session.add(SuppressionEntry(email="optout@ledgerline.example", reason=SuppressionReason.OPT_OUT))
    await session.commit()
    suppressed = await with_hunter_key.post(
        f"/outreach/{failed['id']}/contact", json={"email": "optout@ledgerline.example"}
    )
    assert suppressed.json()["detail"]["code"] == "suppressed"

    response = await with_hunter_key.post(
        f"/outreach/{failed['id']}/contact",
        json={"email": "Priya@Ledgerline.example", "full_name": "Priya Nair", "title": "Engineering Manager"},
    )
    assert response.status_code == 200, response.text
    revived = response.json()
    assert revived["status"] == "drafting"
    assert revived["failure_reason"] is None
    assert revived["contact"]["email"] == "priya@ledgerline.example"
    assert revived["contact"]["role_category"] == "eng_manager"
    assert revived["contact"]["email_source"] == "manual"
    events = (await session.scalars(select(OutreachEvent).order_by(OutreachEvent.created_at))).all()
    assert [e.type for e in events] == [
        OutreachEventType.FAILED,
        OutreachEventType.CONTACT_CHANGED,
        OutreachEventType.RETRIED,
    ]


async def test_manual_contact_respects_the_global_cooldown_and_needs_a_key(
    auth_client: AsyncClient, session: AsyncSession, fake_contacts: FakeContactProvider
) -> None:
    await scored_user(session, await _me(auth_client))
    match = await _top_match(auth_client)
    outreach = (await auth_client.post(f"/matches/{match['id']}/find-contact")).json()
    assert outreach["failure_reason"] == "contact_key_required"  # no Hunter key, nothing cached

    no_key = await auth_client.post(
        f"/outreach/{outreach['id']}/contact", json={"email": "x@ledgerline.example"}
    )
    assert no_key.status_code == 428

    await auth_client.put("/settings/hunter-key", json={"api_key": "hunter-test-key-123"})
    session.add(
        Contact(
            company_id=uuid.UUID(outreach["company"]["id"]),
            full_name="Recently Emailed",
            email="recent@ledgerline.example",
            email_source="hunter",
            last_contacted_at=datetime.now(UTC) - timedelta(days=5),
        )
    )
    await session.commit()
    cooled = await auth_client.post(
        f"/outreach/{outreach['id']}/contact", json={"email": "recent@ledgerline.example"}
    )
    assert cooled.status_code == 409
    assert cooled.json()["detail"]["code"] == "contact_cooldown"


async def test_one_active_outreach_per_company(
    with_hunter_key: AsyncClient, session: AsyncSession, fake_contacts: FakeContactProvider
) -> None:
    ids = await scored_user(session, await _me(with_hunter_key))
    # Make the other Ledgerline job (senior, full-time) a visible match too.
    await session.execute(
        update(JobMatch).where(JobMatch.job_id == ids["relevant"]).values(status=JobMatchStatus.NEW)
    )
    session.add(JobMatch(user_id=await _me(with_hunter_key), job_id=ids["wrong_type"], llm_score=80))
    await session.commit()
    items = (await with_hunter_key.get("/matches", params={"min_score": 0, "limit": 50})).json()["items"]
    ledgerline = {i["job"]["title"]: i["id"] for i in items if i["job"]["company"]["name"] == "Ledgerline"}
    assert set(ledgerline) == {"Backend Engineering Intern"}  # full-time one is filtered by prefs
    assert (
        await with_hunter_key.post(f"/matches/{ledgerline['Backend Engineering Intern']}/find-contact")
    ).status_code == 200

    other = await session.scalar(select(JobMatch).where(JobMatch.job_id == ids["wrong_type"]))
    assert other is not None
    response = await with_hunter_key.post(f"/matches/{other.id}/find-contact")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "outreach_exists"


async def test_other_users_cannot_see_or_change_an_outreach(
    with_hunter_key: AsyncClient, session: AsyncSession, other_user_headers: dict[str, str]
) -> None:
    await scored_user(session, await _me(with_hunter_key))
    match = await _top_match(with_hunter_key)
    outreach = (await with_hunter_key.post(f"/matches/{match['id']}/find-contact")).json()
    assert (
        await with_hunter_key.get(f"/outreach/{outreach['id']}", headers=other_user_headers)
    ).status_code == 404
    swap = await with_hunter_key.post(
        f"/outreach/{outreach['id']}/contact",
        json={"email": "x@ledgerline.example"},
        headers=other_user_headers,
    )
    assert swap.status_code == 404
    assert (await with_hunter_key.get(f"/outreach/{outreach['id']}")).json()["id"] == outreach["id"]


async def test_hunter_key_settings(auth_client: AsyncClient, fake_contacts: FakeContactProvider) -> None:
    status = (await auth_client.get("/settings/hunter-key")).json()
    assert status["configured"] is False
    assert status["monthly_limit"] == 40

    rejected = await auth_client.put("/settings/hunter-key", json={"api_key": "rejected-key-0000"})
    assert rejected.status_code == 400
    assert rejected.json()["detail"]["code"] == "hunter_key_invalid"

    saved = await auth_client.put("/settings/hunter-key", json={"api_key": "hunter-test-key-123"})
    assert saved.json()["configured"] is True
    assert ("check_key", ()) in fake_contacts.calls
    assert "hunter-test-key-123" not in saved.text  # the key is never returned

    assert (await auth_client.delete("/settings/hunter-key")).status_code == 204
    assert (await auth_client.get("/settings/hunter-key")).json()["configured"] is False


async def test_contact_routes_require_auth(client: AsyncClient) -> None:
    some = uuid.uuid4()
    for method, path in [
        ("POST", f"/matches/{some}/find-contact"),
        ("GET", f"/outreach/{some}"),
        ("POST", f"/outreach/{some}/contact"),
        ("GET", "/settings/hunter-key"),
        ("PUT", "/settings/hunter-key"),
        ("DELETE", "/settings/hunter-key"),
    ]:
        assert (await client.request(method, path)).status_code == 401, path
