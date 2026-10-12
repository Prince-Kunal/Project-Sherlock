"""Data isolation (invariant 5, PLAN.md Phase 9): for every API route, user B gets 404 for user A's
resources, B's own lists never show A's data, and nothing B does changes A's data.

Every route of the app is classified below. `test_every_route_is_classified` fails when a route is
added without being put in one of the groups, so new routes can't skip this suite.
"""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, User
from app.models.enums import SizeHint
from tests.prospect_fixtures import TARGET_NAME, add_company_match, add_target
from tests.sending_fixtures import sendable
from tests.test_matches_api import scored_user

# Routes that name one of the caller's resources by id. {match}, {outreach}, {target}, {cmatch} and
# {version} are filled in with user A's; user B must get 404 from every one.
ID_ROUTES: list[tuple[str, str, dict[str, Any] | None]] = [
    ("GET", "/resume/versions/{version}", None),
    ("POST", "/matches/{match}/shortlist", None),
    ("POST", "/matches/{match}/hide", None),
    ("POST", "/matches/{match}/restore", None),
    ("POST", "/matches/{match}/tailor-preview", None),
    ("GET", "/matches/{match}/tailored.pdf", None),
    ("POST", "/matches/{match}/find-contact", None),
    ("POST", "/matches/{match}/draft", None),
    ("GET", "/outreach/{outreach}", None),
    ("PATCH", "/outreach/{outreach}", {"subject": "Taken over"}),
    ("POST", "/outreach/{outreach}/regenerate", {"hint": "shorter"}),
    ("POST", "/outreach/{outreach}/approve", None),
    ("POST", "/outreach/{outreach}/skip", None),
    ("POST", "/outreach/{outreach}/retry", None),
    ("POST", "/outreach/{outreach}/unapprove", None),
    ("PATCH", "/outreach/{outreach}/tracking", {"notes": "B was here"}),
    ("POST", "/outreach/{outreach}/close", None),
    ("GET", "/outreach/{outreach}/timeline", None),
    ("GET", "/outreach/{outreach}/resume.pdf", None),
    ("POST", "/outreach/{outreach}/contact", {"email": "someone@elsewhere.example"}),
    ("PUT", "/prospects/targets/{target}", {"name": "B's now"}),
    ("DELETE", "/prospects/targets/{target}", None),
    ("POST", "/prospects/matches/{cmatch}/queue", None),
    ("POST", "/prospects/matches/{cmatch}/hide", None),
    ("POST", "/prospects/matches/{cmatch}/restore", None),
    ("POST", "/prospects/matches/{cmatch}/draft", None),
]

# GET routes without ids: they answer with the caller's own data (or shared data), never A's.
LIST_ROUTES = [
    "/auth/me",
    "/onboarding",
    "/resume",
    "/resume/versions",
    "/resume/preview.pdf",
    "/resume/ats-check",
    "/preferences",
    "/settings/llm-key",
    "/settings/hunter-key",
    "/settings/apollo-key",
    "/settings/gmail",
    "/settings/quota",
    "/jobs",
    "/matches?min_score=0",
    "/companies/blocked",
    "/outreach",
    "/outreach?status=pending_review",
    "/outreach/stats",
    "/prospects/targets",
    "/prospects/options",
    "/prospects/companies/search?q=Company",
    "/prospects/matches",
]

# Writes without ids: they can only act on the caller's own rows (the user comes from the session).
SELF_SCOPED = {
    ("POST", "/auth/logout"),
    ("POST", "/resume/upload"),
    ("PUT", "/resume"),
    ("POST", "/resume/tag-skills"),
    ("PUT", "/preferences"),
    ("PUT", "/settings/llm-key"),
    ("DELETE", "/settings/llm-key"),
    ("PUT", "/settings/hunter-key"),
    ("DELETE", "/settings/hunter-key"),
    ("PUT", "/settings/apollo-key"),
    ("DELETE", "/settings/apollo-key"),
    ("DELETE", "/settings/gmail"),
    ("DELETE", "/settings/account"),
    ("POST", "/jobs/manual"),
    ("POST", "/matches/refresh"),
    ("POST", "/outreach/build"),
    ("POST", "/prospects/targets"),
    ("POST", "/prospects/companies"),
    ("POST", "/prospects/refresh"),
    ("POST", "/onboarding/complete"),
}

# Shared, not user data: companies are one registry; a block is the caller's own row (checked below).
SHARED = {("POST", "/companies/{company_id}/block"), ("DELETE", "/companies/{company_id}/block")}

PUBLIC = {
    ("GET", "/health"),
    ("POST", "/auth/dev-login"),
    ("GET", "/auth/config"),
    ("GET", "/auth/google/start"),
    ("GET", "/auth/google/callback"),
}


def _template(path: str) -> str:
    """'/outreach/{outreach}' → '/outreach/{outreach_id}' style, to compare with the OpenAPI paths."""
    names = {"match": "match_id", "outreach": "outreach_id", "target": "target_id", "cmatch": "match_id"}
    for short, real in names.items():
        path = path.replace("{" + short + "}", "{" + real + "}")
    return path.split("?")[0]


def test_every_route_is_classified() -> None:
    from app.main import app

    routes = {(m.upper(), p) for p, ops in app.openapi()["paths"].items() for m in ops}
    classified = (
        {(m, _template(p)) for m, p, _ in ID_ROUTES}
        | {("GET", p.split("?")[0]) for p in LIST_ROUTES}
        | SELF_SCOPED
        | SHARED
        | PUBLIC
        | {r for r in routes if r[1].startswith("/admin/")}
    )
    assert routes - classified == set(), "classify new routes in tests/test_isolation.py"
    assert classified - routes == set(), "routes listed here that no longer exist"


@pytest.fixture
async def user_a(auth_client: AsyncClient, session: AsyncSession) -> dict[str, Any]:
    """User A (the dev user, admin) with one of everything: resume, key, scored job matches, an
    outreach in review with its PDF, a prospect target with a company match, and a company block."""
    me = uuid.UUID((await auth_client.get("/auth/me")).json()["id"])
    await scored_user(session, me)
    user = await session.get(User, me)
    assert user is not None
    outreach = await sendable(session, user, approve=False)
    target = await add_target(session, me)
    company = Company(
        name="Isolation Labs", domain="isolation.example", size_hint=SizeHint.STARTUP, description="APIs."
    )
    session.add(company)
    await session.commit()
    cmatch = await add_company_match(session, me, company, target)
    await session.commit()
    matches = (await auth_client.get("/matches", params={"min_score": 0})).json()["items"]
    assert (await auth_client.post(f"/companies/{company.id}/block")).status_code == 200
    return {
        "user": str(me),
        "match": matches[0]["id"],
        "match_ids": [m["id"] for m in matches],
        "outreach": str(outreach.id),
        "target": str(target.id),
        "cmatch": str(cmatch.id),
        "version": "1",
        "blocked": str(company.id),
    }


async def _snapshot(client: AsyncClient, a: dict[str, Any]) -> dict[str, Any]:
    """A's view of everything B might try to change."""
    outreach = (await client.get(f"/outreach/{a['outreach']}")).json()
    return {
        "outreach": {k: outreach[k] for k in ("status", "subject", "body", "notes", "contact")},
        "matches": [
            (m["id"], m["status"]) for m in (await client.get("/matches?min_score=0")).json()["items"]
        ],
        "targets": (await client.get("/prospects/targets")).json(),
        "company_matches": (await client.get("/prospects/matches")).json(),
        "blocked": (await client.get("/companies/blocked")).json(),
        "llm_key": (await client.get("/settings/llm-key")).json()["configured"],
        "preferences": (await client.get("/preferences")).json(),
        "resume": (await client.get("/resume")).json(),
    }


async def test_another_user_gets_404_for_every_route_with_an_id(
    auth_client: AsyncClient, user_a: dict[str, Any], other_user_headers: dict[str, str]
) -> None:
    for path in ("/outreach/{outreach}", "/outreach/{outreach}/timeline", "/outreach/{outreach}/resume.pdf"):
        assert (await auth_client.get(path.format(**user_a))).status_code == 200, path
    assert (await auth_client.get("/resume/versions/1")).status_code == 200
    before = await _snapshot(auth_client, user_a)

    wrong = []
    for method, path, body in ID_ROUTES:
        url = path.format(**user_a)
        response = await auth_client.request(method, url, json=body, headers=other_user_headers)
        if response.status_code != 404:
            wrong.append(f"{method} {path}: {response.status_code} {response.text[:200]}")
    assert wrong == []
    assert await _snapshot(auth_client, user_a) == before


async def test_another_users_lists_never_show_my_data(
    auth_client: AsyncClient, user_a: dict[str, Any], other_user_headers: dict[str, str]
) -> None:
    markers = [
        user_a["user"],
        user_a["outreach"],
        user_a["target"],
        user_a["cmatch"],
        user_a["blocked"],
        *user_a["match_ids"],
        "dev@sherlock.local",
        "rohan@example.com",  # A's resume
        TARGET_NAME,
    ]
    leaks = []
    for path in LIST_ROUTES:
        response = await auth_client.get(path, headers=other_user_headers)
        assert response.status_code < 500, path
        leaks += [f"{path}: {marker}" for marker in markers if marker in response.text]
    assert leaks == []
    stats = (await auth_client.get("/outreach/stats", headers=other_user_headers)).json()
    mine = (await auth_client.get("/outreach/stats")).json()
    assert stats != mine


async def test_another_users_own_writes_leave_my_data_alone(
    auth_client: AsyncClient, user_a: dict[str, Any], other_user_headers: dict[str, str]
) -> None:
    before = await _snapshot(auth_client, user_a)
    b = other_user_headers
    prefs = (await auth_client.get("/preferences", headers=b)).json()
    assert (
        await auth_client.put("/preferences", json={**prefs, "paused": True}, headers=b)
    ).status_code == 200
    assert (await auth_client.delete("/settings/llm-key", headers=b)).status_code == 204
    assert (await auth_client.delete("/settings/hunter-key", headers=b)).status_code == 204
    assert (await auth_client.delete("/settings/gmail", headers=b)).status_code == 204
    assert (await auth_client.post(f"/companies/{user_a['blocked']}/block", headers=b)).status_code == 200
    assert (await auth_client.delete(f"/companies/{user_a['blocked']}/block", headers=b)).status_code == 204
    target = await auth_client.post("/prospects/targets", json={"name": "B's target"}, headers=b)
    assert target.status_code == 201
    done = await auth_client.post("/onboarding/complete", json={"start": False}, headers=b)
    assert done.status_code == 200
    deleted = await auth_client.request(
        "DELETE", "/settings/account", json={"confirm_email": "other@example.com"}, headers=b
    )
    assert deleted.status_code == 204
    # The response clears the session cookie, and this test client shares one jar for both users.
    assert (await auth_client.post("/auth/dev-login")).status_code == 200
    assert await _snapshot(auth_client, user_a) == before


async def test_admin_routes_are_refused_to_other_users(
    auth_client: AsyncClient, other_user_headers: dict[str, str]
) -> None:
    from app.main import app

    admin_routes = [
        (m.upper(), p) for p, ops in app.openapi()["paths"].items() for m in ops if p.startswith("/admin/")
    ]
    assert len(admin_routes) >= 8
    for method, path in admin_routes:
        url = path.replace("{email}", "dev@sherlock.local")
        response = await auth_client.request(method, url, json={}, headers=other_user_headers)
        assert response.status_code == 403, (method, path, response.status_code)
