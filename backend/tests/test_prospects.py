"""Phase 8: open outreach. Company search (YC directory), target filters, website text, company
matching, the contact waterfall, open-outreach tailoring and drafting (invariant 10), the daily split
between job and open drafts, the upgrade path, and the prospects API."""

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.redis import get_redis
from app.models import (
    Company,
    CompanyMatch,
    Contact,
    Job,
    JobMatch,
    Outreach,
    OutreachEvent,
    ProspectTarget,
    UsageLedger,
    User,
    UserCompanyBlock,
    UserPreferences,
)
from app.models.enums import (
    CampaignType,
    CompanyMatchStatus,
    EmailSource,
    JobMatchStatus,
    JobSourceType,
    OutreachEventType,
    OutreachStatus,
    RoleCategory,
    ServiceKeyType,
    SizeHint,
    VerificationStatus,
)
from app.schemas.outreach import EmailDraft
from app.services.contacts.fake import FakeContactProvider
from app.services.contacts.finder import ContactFinder
from app.services.contacts.keys import save_service_key
from app.services.contacts.service import build_finder, record_contact_usage
from app.services.email.drafter import Drafter, DraftError, compose_body, opening_claims, validate_draft
from app.services.email.followups import Followups
from app.services.email.pipeline import DraftPipeline, split_batch
from app.services.embeddings.fake import FakeEmbedder
from app.services.llm.fake import FakeLLMClient
from app.services.prospects.discovery import Discovery, upsert_company
from app.services.prospects.fake import FakeCompanySearch, load_yc_fixture
from app.services.prospects.filters import company_location_matches, industry_matches, size_from_count
from app.services.prospects.matching import CompanyMatcher, company_ref
from app.services.prospects.website import WebsiteFetcher, combine
from app.services.prospects.yc import YC_DIRECTORY_URL, YCDirectory, parse_company
from app.services.registry import build_fake_llm_client
from app.services.resume.tailor import OpenBrief, Tailor
from app.services.sources.http import PoliteHttpClient
from app.services.sources.text import normalize_domain
from tests.conftest import FIXTURES, recorded
from tests.fixtures.record_llm import open_draft_inputs
from tests.matching_fixtures import fixture_resume, seed_matching_user
from tests.prospect_fixtures import add_company_match, add_target, seed_yc_companies
from tests.sending_fixtures import MONDAY_11_IST, sendable
from tests.test_matches_api import _me

NOW = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)
YC_RAW: list[dict[str, Any]] = json.loads((FIXTURES / "sources" / "yc" / "companies.json").read_text())


def _raw(slug: str) -> dict[str, Any]:
    return next(item for item in YC_RAW if item["slug"] == slug)


# --- YC directory -----------------------------------------------------------------------------------


def test_yc_entries_parse_and_unusable_ones_are_skipped() -> None:
    algotest = parse_company(_raw("algotest"))
    assert algotest is not None
    assert (algotest.name, algotest.domain, algotest.size_hint) == (
        "AlgoTest",
        "algotest.in",
        SizeHint.STARTUP,
    )
    assert algotest.hq_location == "Delhi, DL, India"
    assert "India" in algotest.locations
    assert "fintech" in algotest.industry_tags
    assert algotest.description
    assert algotest.description.startswith(_raw("algotest")["one_liner"].strip())
    assert parse_company(_raw("aerotime")) is None  # inactive
    assert parse_company(_raw("contour")) is None  # no website: no one to email
    # The tracking query string on a website doesn't end up in the domain.
    assert parse_company(_raw("100x")).domain == "100x.bot"  # type: ignore[union-attr]
    assert len(load_yc_fixture()) == 11


def test_normalize_domain_drops_paths_queries_and_fragments() -> None:
    assert normalize_domain("https://www.Example.com/about?utm=x#top") == "example.com"
    assert normalize_domain("100x.bot?utm_source=yc") == "100x.bot"
    assert normalize_domain("pragmaticleaders.io, https://ankai.io") == "pragmaticleaders.io"
    assert normalize_domain("") is None


async def test_yc_directory_filters_and_pages() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(200, json=YC_RAW)

    http = PoliteHttpClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)), min_interval_seconds=0)
    directory = YCDirectory(http)
    india = await directory.search_companies([], ["India"], [], page=1)
    assert {c.domain for c in india} >= {"algotest.in", "acciojob.com", "algouniversity.com"}
    assert not any(c.domain in {"10xdental.com", "abstra.io", "9gag.com"} for c in india)
    fintech = await directory.search_companies(["Fintech"], [], ["startup"])
    assert [c.domain for c in fintech] == ["algotest.in"]
    assert await directory.search_companies([], [], [], page=2) == []
    assert requests == [YC_DIRECTORY_URL]  # fetched once, then filtered in memory


# --- Target filters ---------------------------------------------------------------------------------


def test_industry_matching() -> None:
    assert industry_matches(["fintech", "no-code"], None, ["Fintech"])
    assert industry_matches(["b2b", "artificial intelligence"], None, ["AI"])
    assert industry_matches(["engineering, product and design"], None, ["Engineering"])
    assert industry_matches(["education", "edtech"], None, ["EdTech"])
    assert not industry_matches(["healthcare"], None, ["Fintech", "AI"])
    assert industry_matches([], None, [])  # no filter


def test_location_matching_per_place() -> None:
    assert company_location_matches(["Delhi, DL, India", "India", "South Asia"], ["India"])
    assert company_location_matches(["Gurugram, HR, India"], ["Delhi NCR"])
    assert not company_location_matches(
        ["San Francisco, CA, USA", "Remote", "United States of America"], ["India"]
    )
    assert company_location_matches(["São Paulo, SP, Brazil", "Remote", "Brazil"], ["Remote"])
    assert company_location_matches([], ["India"])  # unknown: matching decides


def test_size_from_head_count() -> None:
    assert [size_from_count(n) for n in (None, 3, 50, 51, 500, 501)] == [
        SizeHint.UNKNOWN,
        SizeHint.STARTUP,
        SizeHint.STARTUP,
        SizeHint.MID,
        SizeHint.MID,
        SizeHint.LARGE,
    ]


# --- Website text -----------------------------------------------------------------------------------

HOME = """<html><head><title>Ledgerline</title><script>var x=1;</script></head><body>
<nav><a href="/">Home</a><a href="/about-us">About</a><a href="/careers">Careers</a><a href="/blog">Blog</a></nav>
<h1>Accounting APIs for banks</h1><p>Ledgerline builds APIs that banks call to reconcile payments in real time.</p>
<footer>© Ledgerline · Privacy</footer></body></html>"""
ABOUT = "<html><body><nav>Home About</nav><p>We are twelve engineers in Bengaluru.</p></body></html>"
BLOG = """<html><body><a href="/blog/tag/news">News</a><a href="/blog/how-we-cut-latency">How we cut latency</a>
<a href="/blog/older-post">Older</a></body></html>"""
POST = """<html><body><article><h1>How we cut latency</h1><p>We moved reconciliation from nightly batches to a
streaming pipeline on Postgres logical replication, and p95 latency dropped from minutes to seconds. This is a
long enough article body for readability to keep, with a few more sentences about the work and the team.</p>
</article></body></html>"""


def _site(pages: dict[str, tuple[int, str]], seen: list[str] | None = None) -> PoliteHttpClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request.url.path)
        status_code, body = pages.get(request.url.path, (404, "not found"))
        content_type = "text/plain" if request.url.path == "/robots.txt" else "text/html"
        return httpx.Response(status_code, text=body, headers={"content-type": content_type})

    return PoliteHttpClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)), min_interval_seconds=0)


async def test_website_text_from_home_about_careers_and_latest_post() -> None:
    seen: list[str] = []
    http = _site(
        {
            "/robots.txt": (200, "User-agent: *\nDisallow: /careers"),
            "/": (200, HOME),
            "/about-us": (200, ABOUT),
            "/careers": (200, "<p>should not be read</p>"),
            "/blog": (200, BLOG),
            "/blog/how-we-cut-latency": (200, POST),
        },
        seen,
    )
    text = await WebsiteFetcher(http).fetch("ledgerline.example")
    assert text is not None
    assert "Ledgerline builds APIs that banks call to reconcile payments in real time." in text
    assert "We are twelve engineers in Bengaluru." in text
    assert "streaming pipeline on Postgres logical replication" in text
    assert "should not be read" not in text
    assert "/careers" not in seen
    assert "var x" not in text
    assert "Privacy" not in text
    assert seen[0] == "/robots.txt"
    assert len(text) <= 8000


async def test_website_disallowed_or_unreachable() -> None:
    blocked = _site({"/robots.txt": (200, "User-agent: Sherlock\nDisallow: /"), "/": (200, HOME)})
    assert await WebsiteFetcher(blocked).fetch("ledgerline.example") is None
    down = _site({"/robots.txt": (503, ""), "/": (200, HOME)})
    assert await WebsiteFetcher(down).fetch("ledgerline.example") is None


def test_combine_drops_lines_repeated_across_pages() -> None:
    text = combine([("Home", "Menu\nWe build APIs."), ("About", "Menu\nTwelve engineers.")])
    assert text == "Home:\nMenu\nWe build APIs.\n\nAbout:\nTwelve engineers."


# --- Discovery --------------------------------------------------------------------------------------


class _Sites(WebsiteFetcher):
    def __init__(self, texts: dict[str, str]) -> None:
        self.texts = texts
        self.fetched: list[str] = []

    async def fetch(self, domain: str) -> str | None:
        self.fetched.append(domain)
        return self.texts.get(domain)


async def test_discovery_upserts_fetches_websites_and_embeds(session: AsyncSession) -> None:
    user = await seed_matching_user(session)
    await add_target(session, user.id)  # India startups
    seeded = Company(name="AlgoTest (seed)", domain="algotest.in", size_hint=SizeHint.STARTUP)
    session.add(seeded)
    await session.commit()
    sites = _Sites({"algouniversity.com": "AlgoUniversity:\nWe train engineers with live cohorts."})
    discovery = Discovery(FakeCompanySearch(), sites, FakeEmbedder())

    summary = await discovery.run(session, NOW)
    assert summary.targets == 1
    domains = set((await session.scalars(select(Company.domain))).all())
    assert {"algotest.in", "algouniversity.com", "100x.bot", "algosurg.com"} <= domains
    assert "abstra.io" not in domains
    assert "10xdental.com" not in domains
    await session.refresh(seeded)
    assert seeded.name == "AlgoTest (seed)"  # a known name is kept
    assert seeded.description
    assert "fintech" in seeded.industry_tags
    assert "algouniversity.com" in sites.fetched
    university = await session.scalar(select(Company).where(Company.domain == "algouniversity.com"))
    assert university is not None
    assert university.website_text
    assert university.website_fetched_at == NOW
    assert university.embedding is not None
    assert summary.embedded == summary.created + 1  # every new company plus the seeded one

    # Idempotent: nothing new, websites not fetched again within 30 days, nothing re-embedded.
    sites.fetched.clear()
    again = await discovery.run(session, NOW + timedelta(days=1))
    assert (again.created, again.embedded, sites.fetched) == (0, 0, [])


# --- Company matching -------------------------------------------------------------------------------


async def _matcher_user(session: AsyncSession, **target: object) -> tuple[User, dict[str, Company]]:
    user = await seed_matching_user(session)
    companies = await seed_yc_companies(session)
    await Discovery(FakeCompanySearch([]), _Sites({}), FakeEmbedder()).embed_companies(session)
    await add_target(session, user.id, **target)
    return user, companies


def _company_matcher(llm: FakeLLMClient) -> CompanyMatcher:
    return CompanyMatcher(llm=llm, embedder=FakeEmbedder(), redis=get_redis(), settings=get_settings())


async def test_company_matching_scores_fitting_companies_once(session: AsyncSession) -> None:
    user, companies = await _matcher_user(session, locations=[], company_sizes=[])
    session.add(UserCompanyBlock(user_id=user.id, company_id=companies["9gag.com"].id))
    await session.commit()
    llm = FakeLLMClient(responses={"match_company": [recorded("match_company", "yc_companies")]})

    summary = await _company_matcher(llm).match_user(session, user.id, NOW)
    assert summary.scored == 10  # every usable company except the blocked one
    assert summary.llm_calls == 2  # batches of 8
    rows = {c.company_id: c for c in (await session.scalars(select(CompanyMatch))).all()}
    abstra = rows[companies["abstra.io"].id]
    assert abstra.score == 88
    assert "Python" in abstra.angle
    assert abstra.embedding_score is not None
    assert companies["9gag.com"].id not in rows
    [prompt] = [p for _, p in llm.calls[:1]]
    assert "Rohan" not in prompt
    assert "rohan@" not in prompt
    ledger = await session.scalar(
        select(func.sum(UsageLedger.units)).where(UsageLedger.operation == "match_companies")
    )
    assert ledger == 2

    assert (await _company_matcher(llm).match_user(session, user.id, NOW)).candidates == 0  # scored once


async def test_company_filters_includes_excludes_and_recent_contact(session: AsyncSession) -> None:
    user, companies = await _matcher_user(session)  # India, startups
    t = await session.scalar(select(ProspectTarget).where(ProspectTarget.user_id == user.id))
    assert t is not None
    t.include_companies = [companies["abstra.io"].id]  # outside the filters, but asked for
    t.exclude_companies = [companies["algotest.in"].id]
    await session.commit()
    emailed = await sendable(session, user, company="Emailed Co")
    await session.execute(
        update(Outreach)
        .where(Outreach.id == emailed.id)
        .values(status=OutreachStatus.CLOSED, sent_at=NOW - timedelta(days=10))
    )
    emailed_company = await session.get(Company, emailed.company_id)
    assert emailed_company is not None
    emailed_company.description = "We build backend APIs in Python."
    emailed_company.locations = ["Bengaluru, KA, India"]
    t.include_companies = [*t.include_companies, emailed_company.id]
    await session.commit()
    await Discovery(FakeCompanySearch([]), _Sites({}), FakeEmbedder()).embed_companies(session)

    found = await _company_matcher(FakeLLMClient()).candidates(session, user.id, [t], [0.1] * 384, NOW, 50)
    domains = [c.domain for c, _, _ in found]
    assert domains[0] == "abstra.io"  # included companies first
    assert "algotest.in" not in domains  # excluded
    assert emailed_company.domain not in domains  # emailed 10 days ago
    assert "acciojob.com" not in domains  # mid-size, the target wants startups
    assert {"algouniversity.com", "100x.bot", "algosurg.com"} <= set(domains)


async def test_company_matching_without_targets_or_key(session: AsyncSession) -> None:
    user = await seed_matching_user(session)
    assert (await _company_matcher(FakeLLMClient()).match_user(session, user.id, NOW)).stopped == "no_targets"
    no_key = await seed_matching_user(session, email="nokey@example.com", with_key=False)
    await seed_yc_companies(session)
    await Discovery(FakeCompanySearch([]), _Sites({}), FakeEmbedder()).embed_companies(session)
    await add_target(session, no_key.id)
    assert (
        await _company_matcher(FakeLLMClient()).match_user(session, no_key.id, NOW)
    ).stopped == "no_llm_key"


# --- Contact waterfall ------------------------------------------------------------------------------


async def _company(session: AsyncSession, domain: str = "corvid.example") -> Company:
    company = Company(name="Corvid", domain=domain, size_hint=SizeHint.STARTUP, employee_count=20)
    session.add(company)
    await session.commit()
    return company


async def test_waterfall_cached_contacts_first_then_apollo_then_hunter(session: AsyncSession) -> None:
    company = await _company(session)
    apollo = FakeContactProvider(name="apollo", can_verify=False, people=[])  # finds nobody
    hunter = FakeContactProvider(name="hunter")
    finder = ContactFinder(hunter, now=NOW, search_first=[apollo])
    contact = await finder.find(session, company)
    assert [name for name, _ in apollo.calls] == ["search_people"]
    assert next(name for name, _ in hunter.calls) == "search_people"  # asked only after Apollo
    assert contact.full_name == "Asha Rao"
    assert finder.usage.searches_by_provider == {"apollo": 1, "hunter": 1}

    user = await seed_matching_user(session)
    record_contact_usage(session, user.id, finder.usage)
    await session.commit()
    ledger = {
        (r.provider.value, r.operation, r.units)
        for r in (await session.scalars(select(UsageLedger).where(UsageLedger.user_id == user.id))).all()
    }
    assert {("apollo", "apollo_search", 1), ("hunter", "hunter_search", 1)} <= ledger

    # Cached contacts are used first: no provider is asked within 60 days.
    apollo.calls.clear()
    hunter.calls.clear()
    again = await ContactFinder(hunter, now=NOW + timedelta(days=5), search_first=[apollo]).find(
        session, company
    )
    assert again.full_name == "Asha Rao"
    assert apollo.calls == []
    assert hunter.calls == []


async def test_waterfall_stops_at_apollo_when_it_finds_someone(session: AsyncSession) -> None:
    company = await _company(session)
    apollo = FakeContactProvider(
        name="apollo",
        can_verify=False,
        people=[("Meera", "Shah", "Engineering Manager", "engineering", "manager", None)],
    )
    hunter = FakeContactProvider(name="hunter")
    contact = await ContactFinder(hunter, now=NOW, search_first=[apollo]).find(
        session, company, titles=["Engineering Manager"]
    )
    assert contact.full_name == "Meera Shah"
    assert [name for name, _ in hunter.calls] == ["verify"]  # Hunter only verified Apollo's address
    assert apollo.calls[0] == ("search_people", ("corvid.example", "", "Engineering Manager"))


async def test_a_failing_apollo_falls_through_to_hunter(session: AsyncSession) -> None:
    company = await _company(session)
    hunter = FakeContactProvider(name="hunter")
    contact = await ContactFinder(
        hunter, now=NOW, search_first=[FakeContactProvider(name="apollo", can_verify=False, rejected=True)]
    ).find(session, company)
    assert contact.full_name == "Asha Rao"


async def test_target_titles_come_first(session: AsyncSession) -> None:
    company = await _company(session)
    hunter = FakeContactProvider()
    # A startup's rules put the CTO first; the target asks for recruiters.
    contact = await ContactFinder(hunter, now=NOW).find(session, company, titles=["Technical Recruiter"])
    assert contact.full_name == "Neha Kapoor"


async def test_apollo_is_only_used_with_the_users_own_key(session: AsyncSession) -> None:
    user = await seed_matching_user(session)
    await save_service_key(session, user.id, ServiceKeyType.HUNTER, "hunter-test-key-123")
    made: list[str] = []

    def apollo_factory(key: str) -> FakeContactProvider:
        made.append(key)
        return FakeContactProvider(name="apollo", can_verify=False)

    finder = await build_finder(
        session, user.id, lambda _k: FakeContactProvider(), NOW, apollo_factory=apollo_factory
    )
    assert made == []
    assert [p.name for p in finder._searchers] == ["fake"]
    await save_service_key(session, user.id, ServiceKeyType.APOLLO, "apollo-test-key-123")
    finder = await build_finder(
        session, user.id, lambda _k: FakeContactProvider(), NOW, apollo_factory=apollo_factory
    )
    assert made == ["apollo-test-key-123"]
    assert [p.name for p in finder._searchers] == ["apollo", "fake"]


# --- Apollo adapter (shapes from Apollo's docs; not yet verified against real responses) -----------

APOLLO_SEARCH = {
    "total_entries": 2,
    "people": [
        {
            "id": "p1",
            "first_name": "Meera",
            "last_name_obfuscated": "Sh***h",
            "title": "Engineering Manager",
            "has_email": True,
        },
        {
            "id": "p2",
            "first_name": "Ravi",
            "last_name_obfuscated": "Ku***r",
            "title": "CTO",
            "has_email": False,
        },
    ],
}
APOLLO_MATCH = {
    "person": {
        "id": "p1",
        "first_name": "Meera",
        "last_name": "Shah",
        "name": "Meera Shah",
        "title": "Engineering Manager",
        "email": "Meera@Corvid.example",
        "email_status": "verified",
        "seniority": "manager",
        "departments": ["engineering"],
        "organization": {"name": "Corvid"},
    }
}


async def test_apollo_search_enriches_people_with_email() -> None:
    from app.services.contacts.apollo import ApolloProvider

    seen: list[tuple[str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        seen.append((request.url.path, body))
        assert request.headers["x-api-key"] == "apollo-key"
        if request.url.path.endswith("mixed_people/api_search"):
            return httpx.Response(200, json=APOLLO_SEARCH)
        return httpx.Response(200, json=APOLLO_MATCH)

    provider = ApolloProvider("apollo-key", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    result = await provider.search_people(domain="corvid.example", titles=["Engineering Manager"])
    assert [p.email for p in result.people] == ["meera@corvid.example"]
    assert result.people[0].verification == VerificationStatus.VALID
    assert result.people[0].source == EmailSource.APOLLO
    assert seen[0][1]["q_organization_domains_list"] == ["corvid.example"]
    assert seen[0][1]["person_titles"] == ["Engineering Manager"]
    assert [path for path, _ in seen].count("/api/v1/people/match") == 1  # only people with an email
    assert (await provider.search_people(company="Corvid")).people == []  # no domain, no search


async def test_apollo_errors_map_to_provider_errors() -> None:
    from app.services.contacts.apollo import ApolloProvider
    from app.services.contacts.base import ContactProviderAuthError

    def forbidden(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403, json={"error": "This endpoint is only available to Apollo users on paid plans."}
        )

    provider = ApolloProvider("k", httpx.AsyncClient(transport=httpx.MockTransport(forbidden)))
    with pytest.raises(ContactProviderAuthError, match="paid plans"):
        await provider.search_people(domain="corvid.example")


# --- Open-outreach tailoring and drafting (invariant 10) ---------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Would you refer me for the backend intern role you posted?",
        "I saw your opening for a backend intern.",
        "I'm applying for the position.",
        "I know you're hiring for ML engineers.",
        "Is the Backend Intern role still open?",
        "There's an open position on your team, I think.",
    ],
)
def test_opening_claims_are_rejected(text: str) -> None:
    assert [i.code for i in opening_claims("Subject", text)] == ["implies_opening"]


@pytest.mark.parametrize(
    "text",
    [
        "Does your team take interns?",
        "Are there upcoming openings for an intern I should watch for?",
        "I'm looking for a backend internship.",
        "Would you be open to a 15-minute chat, or passing my resume to whoever handles hiring?",
    ],
)
def test_open_asks_pass(text: str) -> None:
    assert opening_claims("Interns at Corvid?", text) == []


async def test_the_open_drafter_rejects_a_claimed_opening_then_gives_up() -> None:
    inputs = open_draft_inputs()
    good = EmailDraft.model_validate(recorded("draft_open_email", "rohan_abstra")[-1])  # type: ignore[index]
    bad = good.model_copy(
        update={"body": "Would you refer me for the backend intern role you posted? My resume is attached."}
    )
    llm = FakeLLMClient(responses={"draft_open_email": [bad.model_dump(), bad.model_dump()]})
    with pytest.raises(DraftError) as caught:
        await Drafter(llm).draft_open(inputs, None)
    assert "implies_opening" in {i.code for i in caught.value.issues}
    _, retry_prompt = llm.calls[1]
    assert "implies_opening" in retry_prompt  # the retry was told why


async def test_the_recorded_open_draft_passes_every_check() -> None:
    inputs = open_draft_inputs()
    drafter = Drafter(
        FakeLLMClient(responses={"draft_open_email": recorded("draft_open_email", "rohan_abstra")})
    )
    result = await drafter.draft_open(inputs, None)
    assert result.body.startswith("Hi Asha,")
    assert result.style_warnings == []
    assert opening_claims(result.subject, result.body) == []
    _, prompt = drafter._llm.calls[0]  # type: ignore[attr-defined]
    assert "whether the team is open to taking an intern" in prompt  # the founder ask
    assert "Rohan" not in prompt.split("## Inputs", 1)[1]
    draft = EmailDraft.model_validate(recorded("draft_open_email", "rohan_abstra")[-1])  # type: ignore[index]
    composed = compose_body(draft, inputs.contact, inputs.basics)
    assert validate_draft(draft, drafter.open_contexts(inputs), composed) == []


async def test_open_tailoring_builds_a_one_page_ats_passing_resume() -> None:
    plans = recorded("tailor_open", "rohan_abstra")
    tailor = Tailor(FakeLLMClient(responses={"tailor_open": plans}))
    company = next(c for c in load_yc_fixture() if c.domain == "abstra.io")
    brief = OpenBrief(
        company=company.name, target_roles=["Backend Intern"], about=company.description or "", angle="x"
    )
    result = await tailor.tailor_open(fixture_resume(), brief, None)
    assert result.ats.passed
    assert result.ats.page_count == 1
    _, prompt = tailor._llm.calls[0]  # type: ignore[attr-defined]
    assert '"company": "Abstra"' in prompt
    assert "## Brief" in prompt


# --- The daily batch: split, fill, and one outreach per company ----------------------------------------


@pytest.mark.parametrize(
    ("room", "share", "jobs", "companies", "expected"),
    [
        (5, 40, 10, 10, (3, 2)),
        (8, 40, 10, 10, (5, 3)),
        (5, 40, 0, 10, (0, 5)),  # only a prospect target: a full batch of open drafts
        (5, 40, 10, 0, (5, 0)),
        (5, 40, 1, 10, (1, 4)),  # jobs short: open outreach fills the gap
        (5, 40, 10, 1, (4, 1)),  # companies short: jobs fill
        (5, 0, 10, 10, (5, 0)),
        (5, 100, 10, 10, (0, 5)),
        (3, 40, 1, 1, (1, 1)),
    ],
)
def test_split_batch(room: int, share: int, jobs: int, companies: int, expected: tuple[int, int]) -> None:
    assert split_batch(room, share, jobs, companies) == expected


async def _drafting_user(session: AsyncSession, batch: int, share: int = 40) -> User:
    user = await seed_matching_user(session)
    await save_service_key(session, user.id, ServiceKeyType.HUNTER, "hunter-test-key-123")
    await session.execute(
        update(UserPreferences)
        .where(UserPreferences.user_id == user.id)
        .values(daily_draft_batch=batch, open_outreach_share=share)
    )
    await session.commit()
    return user


async def _company_matches(session: AsyncSession, user: User, n: int) -> list[CompanyMatch]:
    target = await add_target(session, user.id)
    matches = []
    for i in range(n):
        company = Company(
            name=f"Prospect {i}",
            domain=f"prospect{i}.example",
            size_hint=SizeHint.STARTUP,
            description=f"Prospect {i} builds payment APIs in Python for small banks in India. "
            "Its engineers run everything on PostgreSQL and Docker.",
        )
        session.add(company)
        await session.flush()
        matches.append(await add_company_match(session, user.id, company, target, score=90 - i))
    return matches


async def _job_matches(session: AsyncSession, user: User, n: int) -> list[JobMatch]:
    matches = []
    for i in range(n):
        company = Company(name=f"Hiring {i}", domain=f"hiring{i}.example", size_hint=SizeHint.STARTUP)
        session.add(company)
        await session.flush()
        job = Job(
            company_id=company.id,
            source=JobSourceType.MANUAL,
            title="Backend Engineering Intern",
            location="Bengaluru, India",
            employment_type="internship",
            description_text="Build REST APIs in Python (Django) backed by PostgreSQL. Write tests and ship.",
            url=f"https://hiring{i}.example/jobs/1",
            dedupe_hash=hashlib.sha256(f"job-{i}".encode()).hexdigest(),
            posted_at=datetime.now(UTC) - timedelta(days=1),
        )
        session.add(job)
        await session.flush()
        match = JobMatch(
            user_id=user.id, job_id=job.id, llm_score=88 - i, reasoning="Fixture.", status=JobMatchStatus.NEW
        )
        session.add(match)
        matches.append(match)
    await session.commit()
    return matches


def _pipeline(contacts: FakeContactProvider | None = None) -> DraftPipeline:
    fake = contacts or FakeContactProvider()
    return DraftPipeline(build_fake_llm_client(), lambda _key: fake)


async def test_only_a_prospect_target_gives_a_full_batch_of_open_drafts(session: AsyncSession) -> None:
    user = await _drafting_user(session, batch=3)
    await _company_matches(session, user, 4)
    summary = await _pipeline().build_for_user(session, user.id)
    assert (summary.drafted, summary.failed, summary.planned_open, summary.planned_job) == (3, 0, 3, 0)
    rows = (await session.scalars(select(Outreach).where(Outreach.user_id == user.id))).all()
    assert all(o.campaign_type == CampaignType.OPEN and o.job_id is None for o in rows)
    assert all(o.status == OutreachStatus.PENDING_REVIEW for o in rows)
    for outreach in rows:
        assert outreach.body
        assert opening_claims(outreach.subject or "", outreach.body) == []
        contact = await session.get(Contact, outreach.contact_id)
        assert contact is not None
        assert contact.title == "Co-founder & CTO"
        assert (outreach.tailored_resume or {}).get("ats", {}).get("passed") is True
    statuses = set((await session.scalars(select(CompanyMatch.status))).all())
    assert statuses == {CompanyMatchStatus.CONTACTED, CompanyMatchStatus.NEW}  # 3 used, 1 left


async def test_both_kinds_get_the_configured_split(session: AsyncSession) -> None:
    user = await _drafting_user(session, batch=5, share=40)
    await _job_matches(session, user, 4)
    await _company_matches(session, user, 4)
    summary = await _pipeline().build_for_user(session, user.id)
    assert (summary.planned_job, summary.planned_open, summary.drafted) == (3, 2, 5)
    modes = (await session.scalars(select(Outreach.campaign_type).where(Outreach.user_id == user.id))).all()
    assert sorted(m.value for m in modes) == ["job", "job", "job", "open", "open"]


async def test_when_jobs_run_short_open_outreach_fills_the_gap(session: AsyncSession) -> None:
    user = await _drafting_user(session, batch=4, share=25)
    await _job_matches(session, user, 1)
    await _company_matches(session, user, 5)
    summary = await _pipeline().build_for_user(session, user.id)
    assert (summary.planned_job, summary.planned_open) == (1, 3)


async def test_one_outreach_per_company_across_both_modes(session: AsyncSession) -> None:
    user = await _drafting_user(session, batch=4, share=50)
    [job_match] = await _job_matches(session, user, 1)
    job = await session.get(Job, job_match.job_id)
    assert job is not None
    target = await add_target(session, user.id)
    same_company = await session.get(Company, job.company_id)
    assert same_company is not None
    same_company.description = "Hiring 0 builds payment APIs in Python for banks. It runs on PostgreSQL."
    await add_company_match(session, user.id, same_company, target)
    summary = await _pipeline().build_for_user(session, user.id)
    assert summary.drafted == 1
    count = await session.scalar(
        select(func.count()).select_from(Outreach).where(Outreach.company_id == same_company.id)
    )
    assert count == 1


async def test_no_company_text_fails_before_any_contact_lookup(session: AsyncSession) -> None:
    user = await _drafting_user(session, batch=1, share=100)
    [match] = await _company_matches(session, user, 1)
    await session.execute(update(Company).where(Company.id == match.company_id).values(description=None))
    await session.commit()
    contacts = FakeContactProvider()
    summary = await _pipeline(contacts).build_for_user(session, user.id)
    assert summary.failed == 1
    outreach = await session.scalar(select(Outreach).where(Outreach.user_id == user.id))
    assert outreach is not None
    assert outreach.failure_reason == "no_company_context"
    assert contacts.calls == []


# --- Upgrade path --------------------------------------------------------------------------------------


async def test_a_new_matching_job_upgrades_the_open_outreach_and_its_follow_up_names_it(
    session: AsyncSession,
) -> None:
    user = await seed_matching_user(session)
    outreach = await sendable(session, user, company="Corvid")
    await session.execute(
        update(Outreach)
        .where(Outreach.id == outreach.id)
        .values(status=OutreachStatus.SENT, sent_at=MONDAY_11_IST - timedelta(days=2), gmail_thread_id="t-1")
    )
    job = Job(
        company_id=outreach.company_id,
        source=JobSourceType.MANUAL,
        title="Backend Engineering Intern",
        location="Bengaluru, India",
        employment_type="internship",
        description_text="Build REST APIs in Python.",
        dedupe_hash=hashlib.sha256(b"corvid-intern").hexdigest(),
        posted_at=MONDAY_11_IST - timedelta(days=1),
    )
    session.add(job)
    await session.flush()
    match = JobMatch(
        user_id=user.id, job_id=job.id, llm_score=85, reasoning="Fixture.", status=JobMatchStatus.NEW
    )
    session.add(match)
    await session.commit()

    nudge = {
        "body": "Since I wrote, I saw Corvid posted a Backend Engineering Intern opening. Would you be open to referring me for it, or pointing me to whoever's hiring?"
    }
    llm = FakeLLMClient(responses={"draft_followup": nudge})
    summary = await Followups(llm).run_for_user(session, user.id, MONDAY_11_IST)
    assert (summary.upgraded, summary.drafted) == (1, 1)  # drafted now, not after followup_after_days
    await session.refresh(outreach)
    assert outreach.campaign_type == CampaignType.JOB
    assert outreach.job_id == job.id
    assert outreach.status == OutreachStatus.PENDING_REVIEW
    assert outreach.followup_count == 1
    assert outreach.gmail_thread_id == "t-1"  # in the same thread
    assert outreach.body is not None
    assert "Backend Engineering Intern" in outreach.body
    [(_, prompt)] = llm.calls
    assert '"new_opening": "Backend Engineering Intern"' in prompt
    events = (
        await session.scalars(select(OutreachEvent.type).where(OutreachEvent.outreach_id == outreach.id))
    ).all()
    assert OutreachEventType.UPGRADED_TO_JOB in events
    await session.refresh(match)
    assert match.status == JobMatchStatus.IN_PIPELINE
    assert (
        await session.scalar(select(func.count()).select_from(Outreach).where(Outreach.user_id == user.id))
        == 1
    )

    # A follow-up that doesn't name the new opening is rejected.
    from app.services.email.followups import validate_followup

    issues = validate_followup(
        "Re: x",
        "Following up on my note.",
        "Following up. I won't follow up.",
        new_opening="Backend Engineering Intern",
    )
    assert "missing_opening" in {i.code for i in issues}


async def test_an_open_follow_up_without_a_new_job_never_claims_an_opening() -> None:
    from app.services.email.followups import validate_followup

    body = "Following up on the backend intern role you posted."
    issues = validate_followup("Re: x", body, body + " I won't follow up.", open_outreach=True)
    assert "implies_opening" in {i.code for i in issues}


# --- API ---------------------------------------------------------------------------------------------


async def test_targets_crud_and_isolation(
    with_llm_key: AsyncClient, session: AsyncSession, other_user_headers: dict[str, str]
) -> None:
    companies = await seed_yc_companies(session)
    body = {
        "name": "Fintech in India",
        "target_roles": ["Backend Intern"],
        "contact_titles": ["CTO", "CTO", "Engineering Manager"],
        "industries": ["Fintech"],
        "locations": ["India"],
        "company_sizes": ["startup"],
        "include_companies": [str(companies["abstra.io"].id), str(uuid.uuid4())],
        "exclude_companies": [],
    }
    created = await with_llm_key.post("/prospects/targets", json=body)
    assert created.status_code == 201, created.text
    target = created.json()
    assert target["contact_titles"] == ["CTO", "Engineering Manager"]  # deduplicated
    assert [c["domain"] for c in target["include_companies"]] == ["abstra.io"]  # unknown ids dropped
    updated = await with_llm_key.put(f"/prospects/targets/{target['id']}", json={**body, "is_active": False})
    assert updated.json()["is_active"] is False
    assert len((await with_llm_key.get("/prospects/targets")).json()) == 1

    with_llm_key.cookies.clear()
    assert (await with_llm_key.get("/prospects/targets", headers=other_user_headers)).json() == []
    for method in ("PUT", "DELETE"):
        response = await with_llm_key.request(
            method, f"/prospects/targets/{target['id']}", json=body, headers=other_user_headers
        )
        assert response.status_code == 404


async def test_company_matches_api_actions_and_draft_now(
    with_hunter_key: AsyncClient, session: AsyncSession, other_user_headers: dict[str, str]
) -> None:
    user_id = await _me(with_hunter_key)
    user = await session.get(User, user_id)
    assert user is not None
    await seed_matching_user(session, user=user)
    [first, second] = await _company_matches(session, user, 2)

    feed = (await with_hunter_key.get("/prospects/matches")).json()
    assert [i["company"]["name"] for i in feed["items"]] == ["Prospect 0", "Prospect 1"]
    assert feed["items"][0]["target_name"] == "Indian startups"
    queued = (await with_hunter_key.post(f"/prospects/matches/{second.id}/queue")).json()
    assert queued["status"] == "queued"
    feed = (await with_hunter_key.get("/prospects/matches")).json()
    assert feed["items"][0]["id"] == str(second.id)  # queued first
    assert (await with_hunter_key.post(f"/prospects/matches/{second.id}/hide")).json()["status"] == "hidden"
    assert (await with_hunter_key.get("/prospects/matches")).json()["total"] == 1
    assert (await with_hunter_key.post(f"/prospects/matches/{second.id}/draft")).status_code == 409

    drafted = await with_hunter_key.post(f"/prospects/matches/{first.id}/draft")
    assert drafted.status_code == 200, drafted.text
    detail = drafted.json()
    assert detail["status"] == "pending_review"
    assert detail["campaign_type"] == "open"
    assert detail["job"] is None
    assert detail["angle"] == first.angle
    assert detail["target_name"] == "Indian startups"
    assert detail["company_about"].startswith("Prospect 0 builds payment APIs")
    assert detail["personalization_source"]

    # Editing in a claim that an opening exists is refused (invariant 10), and so is approving one.
    edited = await with_hunter_key.patch(
        f"/outreach/{detail['id']}",
        json={
            "body": detail["body"].replace("Resume's attached.", "Resume's attached for the role you posted.")
        },
    )
    assert edited.status_code == 422
    assert "No opening is posted" in edited.json()["detail"]["message"]
    await session.execute(
        update(Outreach)
        .where(Outreach.id == uuid.UUID(detail["id"]))
        .values(body=detail["body"] + "\nI'm applying for the position.")
    )
    await session.commit()
    assert (await with_hunter_key.post(f"/outreach/{detail['id']}/approve")).status_code == 422

    listed = (await with_hunter_key.get("/outreach", params={"campaign_type": "open"})).json()
    assert listed["total"] == 1
    assert (await with_hunter_key.get("/outreach", params={"campaign_type": "job"})).json()["total"] == 0
    stats = (await with_hunter_key.get("/outreach/stats")).json()
    assert stats["new_company_matches"] == 0  # one contacted, one hidden

    with_hunter_key.cookies.clear()
    assert (await with_hunter_key.get("/prospects/matches", headers=other_user_headers)).json()["total"] == 0
    for action in ("queue", "hide", "restore", "draft"):
        response = await with_hunter_key.post(
            f"/prospects/matches/{first.id}/{action}", headers=other_user_headers
        )
        assert response.status_code == 404, action


async def test_options_company_search_and_adding_a_company(
    auth_client: AsyncClient, session: AsyncSession
) -> None:
    await seed_yc_companies(session)
    options = (await auth_client.get("/prospects/options")).json()
    assert "fintech" in options["industries"]
    assert options["companies_known"] == 11
    found = (await auth_client.get("/prospects/companies/search", params={"q": "algo"})).json()
    assert {c["domain"] for c in found} >= {"algotest.in", "algouniversity.com"}
    added = await auth_client.post("/prospects/companies", json={"domain": "https://www.corvid.dev/about"})
    assert added.status_code == 200
    assert added.json()["domain"] == "corvid.dev"
    assert added.json()["name"] == "Corvid"
    again = await auth_client.post("/prospects/companies", json={"domain": "corvid.dev"})
    assert again.json()["id"] == added.json()["id"]
    assert (await auth_client.post("/prospects/companies", json={"domain": "not a site"})).status_code == 422


async def test_apollo_key_settings(auth_client: AsyncClient) -> None:
    assert (await auth_client.get("/settings/apollo-key")).json()["configured"] is False
    saved = await auth_client.put("/settings/apollo-key", json={"api_key": "apollo-test-key-123"})
    assert saved.status_code == 200
    assert saved.json()["configured"] is True
    assert (await auth_client.delete("/settings/apollo-key")).status_code == 204
    assert (await auth_client.get("/settings/apollo-key")).json()["configured"] is False


async def test_prospect_routes_require_auth(client: AsyncClient) -> None:
    for method, path in [
        ("GET", "/prospects/targets"),
        ("POST", "/prospects/targets"),
        ("GET", "/prospects/matches"),
        ("GET", "/prospects/options"),
        ("POST", "/prospects/refresh"),
        ("GET", "/settings/apollo-key"),
    ]:
        assert (await client.request(method, path)).status_code == 401, path


def test_company_ref_is_stable_and_domain_based() -> None:
    a = Company(name="Abstra", domain="abstra.io")
    assert company_ref(a) == company_ref(Company(name="Other name", domain="abstra.io"))
    assert len(company_ref(a)) == 8


async def test_upsert_company_keeps_known_size(session: AsyncSession) -> None:
    company = Company(name="AlgoTest", domain="algotest.in", size_hint=SizeHint.MID, employee_count=120)
    session.add(company)
    await session.commit()
    found = parse_company(_raw("algotest"))
    assert found is not None
    same, created = await upsert_company(session, found)
    assert not created
    assert same.id == company.id
    assert (same.size_hint, same.employee_count) == (SizeHint.MID, 120)
    assert same.embedding is None  # a new description is re-embedded


def test_role_category_drives_the_open_ask() -> None:
    from app.services.email.drafter import OPEN_ROLE_ASK, looking_for

    assert looking_for([], ["internship"]) == ("an internship", "an intern")
    assert looking_for(["Data Engineer"], ["full_time"]) == ("Data Engineer", "a junior engineer")
    assert "15-minute chat" in OPEN_ROLE_ASK[RoleCategory.ENG_MANAGER]
    assert "upcoming openings" in OPEN_ROLE_ASK[RoleCategory.RECRUITER]
