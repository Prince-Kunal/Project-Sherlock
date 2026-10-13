"""Warm paths (PLAN.md Phase 10): the user's own connections list flags companies where they know
someone, and who went to their college. Never sent to the LLM, never emailed."""

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, Contact, User
from app.services.connections import (
    ConnectionsFileError,
    company_key,
    parse_connections_csv,
    replace_connections,
    warm_paths,
)
from tests.sending_fixtures import sendable
from tests.test_matches_api import scored_user

LINKEDIN = b"""Notes:
"When exporting your connection data, you may notice that some of the email addresses are missing."

First Name,Last Name,URL,Email Address,Company,Position,Connected On
Priya,Nair,https://www.linkedin.com/in/priya-nair,,Ledgerline Software Private Limited,Engineering Manager,03 Oct 2026
Arjun,Rao,https://www.linkedin.com/in/arjun-rao,,Brightcart,SDE II,01 Sep 2026
,,,,,,
Meera,Iyer,,,Bayline Robotics Inc.,Recruiter,12 Aug 2026
"""

ALUMNI_CSV = b"""Name,Company,College,Title
Kabir Shah,Ledgerline,Example School of Technology,Backend Engineer
Dev Patel,ferrovia,Some Other University,SRE
"""


def test_linkedin_export_and_plain_csv_parse() -> None:
    people = parse_connections_csv(LINKEDIN)
    assert [(p.full_name, p.company, p.position) for p in people] == [
        ("Priya Nair", "Ledgerline Software Private Limited", "Engineering Manager"),
        ("Arjun Rao", "Brightcart", "SDE II"),
        ("Meera Iyer", "Bayline Robotics Inc.", "Recruiter"),
    ]
    assert people[0].profile_url == "https://www.linkedin.com/in/priya-nair"
    plain = parse_connections_csv(ALUMNI_CSV)
    assert (plain[0].full_name, plain[0].school, plain[0].position) == (
        "Kabir Shah",
        "Example School of Technology",
        "Backend Engineer",
    )
    try:
        parse_connections_csv(b"just,some,columns\n1,2,3\n")
    except ConnectionsFileError:
        pass
    else:
        raise AssertionError("a file without name/company columns must be refused")


def test_company_names_are_matched_without_legal_suffixes() -> None:
    assert company_key("Ledgerline Software Private Limited") == "ledgerline"
    assert company_key("Bayline Robotics Inc.") == "bayline robotics"
    assert company_key("Tech Mahindra") == "tech mahindra"
    assert company_key("Labs") == "labs"


async def test_warm_paths_by_name_and_domain_with_alumni_first(session: AsyncSession) -> None:
    from tests.matching_fixtures import seed_matching_user

    user = await seed_matching_user(session)  # education: Example School of Technology
    await replace_connections(
        session, user.id, parse_connections_csv(LINKEDIN) + parse_connections_csv(ALUMNI_CSV)
    )
    ledgerline = Company(name="Ledgerline", domain="ledgerline.example")
    ferrovia = Company(name="Ferrovia Cloud", domain="ferrovia.example")
    nobody = Company(name="Nobody Co", domain="nobody.example")
    session.add_all([ledgerline, ferrovia, nobody])
    await session.commit()

    paths = await warm_paths(session, user.id, [ledgerline, ferrovia, nobody])
    assert set(paths) == {ledgerline.id, ferrovia.id}
    assert (paths[ledgerline.id].count, paths[ledgerline.id].alumni) == (2, 1)
    assert [p.name for p in paths[ledgerline.id].people] == ["Kabir Shah", "Priya Nair"]  # alumni first
    assert paths[ferrovia.id].people[0].name == "Dev Patel"  # matched by the domain stem

    other = User(email="someone@else.example", name="Else")
    session.add(other)
    await session.commit()
    assert await warm_paths(session, other.id, [ledgerline]) == {}  # invariant 5


async def test_api_upload_summary_hints_and_delete(auth_client: AsyncClient, session: AsyncSession) -> None:
    me = uuid.UUID((await auth_client.get("/auth/me")).json()["id"])
    await scored_user(session, me)
    empty = (await auth_client.get("/connections")).json()
    assert (empty["count"], empty["uploaded_at"]) == (0, None)
    bad = await auth_client.post("/connections", files={"file": ("c.csv", b"a,b\n1,2\n", "text/csv")})
    assert bad.status_code == 422

    up = await auth_client.post(
        "/connections", files={"file": ("Connections.csv", LINKEDIN + b"", "text/csv")}
    )
    assert up.status_code == 200, up.text
    assert (up.json()["count"], up.json()["companies"]) == (3, 3)

    matches = (await auth_client.get("/matches", params={"min_score": 0})).json()["items"]
    hinted = {m["job"]["company"]["name"]: m["warm_path"] for m in matches}
    assert hinted["Ledgerline"]["people"][0]["name"] == "Priya Nair"
    assert hinted["Ledgerline"]["people"][0]["position"] == "Engineering Manager"

    # The review card says when the draft is addressed to someone the user knows.
    user = await session.get(User, me)
    assert user is not None
    outreach = await sendable(session, user, approve=False, company="Brightcart")
    contact = await session.get(Contact, outreach.contact_id)
    assert contact is not None
    contact.full_name = "Arjun Rao"
    await session.commit()
    detail = (await auth_client.get(f"/outreach/{outreach.id}")).json()
    assert detail["warm_path"]["count"] == 1
    assert detail["knows_contact"] is True

    assert (await auth_client.delete("/connections")).status_code == 204
    assert (await auth_client.get("/connections")).json()["count"] == 0
    assert all(
        m["warm_path"] is None
        for m in (await auth_client.get("/matches", params={"min_score": 0})).json()["items"]
    )
