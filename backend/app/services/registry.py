"""Picks real or fake implementations of every external service (PLAN.md §12, USE_FAKES).

Everything that talks to the outside world is obtained here, so tests and `USE_FAKES=true` swap
the whole app onto fakes without touching call sites.
"""

import hashlib
import json
import re
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.redis import get_redis
from app.models import User
from app.services.contacts.apollo import ApolloProvider
from app.services.contacts.base import ContactProvider
from app.services.contacts.fake import FakeContactProvider
from app.services.contacts.hunter import HunterProvider
from app.services.email.connection import GmailAccess, GmailFactory
from app.services.email.fake_gmail import FakeGmailClient
from app.services.email.gmail import GmailClient
from app.services.embeddings.bge import BgeEmbedder
from app.services.embeddings.embedder import Embedder
from app.services.embeddings.fake import FakeEmbedder
from app.services.google.oauth import GoogleOAuth, HttpGoogleOAuth
from app.services.llm.anthropic import AnthropicClient
from app.services.llm.cache import LLMCache
from app.services.llm.client import LLMClient
from app.services.llm.fake import FakeLLMClient
from app.services.llm.gemini import GeminiClient
from app.services.llm.rate_limit import RateLimiter
from app.services.prospects.base import CompanySearchProvider
from app.services.prospects.fake import FakeCompanySearch
from app.services.prospects.website import WebsiteFetcher, website_http
from app.services.prospects.yc import YCDirectory
from app.services.sources.http import PoliteHttpClient

_FAKE_RESPONSES = Path(__file__).parent / "llm" / "fake_responses"


_JOB_REF_RE = re.compile(r'"job_ref": "([0-9a-f]{8})"')


def _fake_match_scores(prompt: str) -> list[dict[str, Any]]:
    """USE_FAKES answer for prompts/match.md: a stable pseudo-random score per job ref."""
    refs = _JOB_REF_RE.findall(prompt.split("## Jobs", 1)[-1])
    return [
        {
            "job_ref": ref,
            "fit_score": 40 + int(hashlib.sha256(ref.encode()).hexdigest(), 16) % 56,
            "employment_type": "unknown",
            "matched_skills": [],
            "missing_must_haves": [],
            "reasoning": "Sample score from the fake LLM (USE_FAKES=true).",
        }
        for ref in refs
    ]


_RESUME_BLOCK_RE = re.compile(r"## Resume\n```json\n(.*?)\n```", re.DOTALL)


def _fake_tailor_plan(prompt: str) -> dict[str, Any]:
    """USE_FAKES answer for prompts/tailor.md: keep every bullet as written, in resume order."""
    match = _RESUME_BLOCK_RE.search(prompt)
    resume: dict[str, Any] = json.loads(match.group(1)) if match else {}
    entries = [*resume.get("education", []), *resume.get("experience", []), *resume.get("projects", [])]
    ids = [b["id"] for e in entries for b in e.get("bullets", [])]
    ids += [b["id"] for b in resume.get("achievements", [])]
    return {
        "section_order": ["education", "experience", "projects", "skills", "achievements"],
        "selected_bullet_ids": ids,
        "rephrasings": [],
        "skills_to_show": [s for items in resume.get("skills", {}).values() for s in items],
        "summary": None,
        "jd_keywords": [],
    }


_INPUTS_BLOCK_RE = re.compile(r"## Inputs\n```json\n(.*?)\n```", re.DOTALL)


def _fake_email_draft(prompt: str) -> dict[str, Any]:
    """USE_FAKES answer for prompts/draft_email.md: a short plain draft (it never quotes its source)."""
    match = _INPUTS_BLOCK_RE.search(prompt)
    inputs: dict[str, Any] = json.loads(match.group(1)) if match else {}
    job = inputs.get("job", {})
    title = job.get("title") or "this role"
    source = (inputs.get("context_sentences") or [title])[0]
    return {
        "subject": f"{title} at {job.get('company', 'your team')}"[:70],
        "body": (
            f"I'm applying for the {title} role and wanted to ask if you'd refer me. The projects at the "
            "top of my resume are the closest to what the team does.\n\nIf you're not the right person, "
            "a pointer to whoever's hiring would help. Resume's attached. (Sample draft from the fake "
            "LLM, USE_FAKES=true.)"
        ),
        "personalization_source": source,
    }


_COMPANY_REF_RE = re.compile(r'"company_ref": "([0-9a-f]{8})"')


def _fake_company_scores(prompt: str) -> list[dict[str, Any]]:
    """USE_FAKES answer for prompts/match_company.md: a stable pseudo-random score per company."""
    refs = _COMPANY_REF_RE.findall(prompt.split("## Companies", 1)[-1])
    return [
        {
            "company_ref": ref,
            "fit_score": 45 + int(hashlib.sha256(ref.encode()).hexdigest(), 16) % 51,
            "angle": "Your backend projects are close to what this company builds.",
            "reasoning": "Sample score from the fake LLM (USE_FAKES=true).",
        }
        for ref in refs
    ]


def _fake_open_email(prompt: str) -> dict[str, Any]:
    """USE_FAKES answer for prompts/draft_open_email.md: a short draft that never implies an opening."""
    match = _INPUTS_BLOCK_RE.search(prompt)
    inputs: dict[str, Any] = json.loads(match.group(1)) if match else {}
    company = inputs.get("company") or "your company"
    return {
        "subject": f"Interns at {company}?"[:70],
        "body": (
            f"I've been building backend projects in Python and wanted to ask whether {company} ever "
            "takes interns. If it's not something you do, a pointer to whoever handles hiring would "
            "help. Resume's attached. (Sample draft from the fake LLM, USE_FAKES=true.)"
        ),
        "personalization_source": (inputs.get("context_sentences") or [company])[0],
    }


def build_fake_llm_client() -> FakeLLMClient:
    """For USE_FAKES=true local runs: canned answers so the UI works without an API key."""
    client = FakeLLMClient()
    for path in sorted(_FAKE_RESPONSES.glob("*.json")):
        client.add_response(path.stem, json.loads(path.read_text()))
    client.add_responder("match", _fake_match_scores)
    client.add_responder("tailor", _fake_tailor_plan)
    client.add_responder("draft_email", _fake_email_draft)
    client.add_responder("match_company", _fake_company_scores)
    client.add_responder("tailor_open", _fake_tailor_plan)
    client.add_responder("draft_open_email", _fake_open_email)
    return client


def build_llm_client(settings: Settings) -> LLMClient:
    if settings.use_fakes:
        return build_fake_llm_client()
    redis = get_redis()
    cache = LLMCache(redis, settings.llm_cache_ttl_seconds)
    if settings.llm_provider == "anthropic":
        return AnthropicClient(cache)
    return GeminiClient(
        default_api_key=settings.gemini_api_key,
        model_smart=settings.llm_model_smart,
        model_fast=settings.llm_model_fast,
        limiter=RateLimiter(redis, rpm=settings.llm_rpm, rpd=settings.llm_rpd),
        cache=cache,
    )


@lru_cache
def get_llm_client() -> LLMClient:
    return build_llm_client(get_settings())


@lru_cache
def get_embedder() -> Embedder:
    settings = get_settings()
    if settings.use_fakes:
        return FakeEmbedder()
    return BgeEmbedder(settings.embed_model, settings.embed_cache_dir)


_fake_contacts = FakeContactProvider(resolve_names=False)


def get_contact_provider_factory() -> Callable[[str], ContactProvider]:
    """A function from a user's Hunter key to a provider (each user brings their own key)."""
    if get_settings().use_fakes:
        return lambda _key: _fake_contacts
    return HunterProvider


def get_apollo_factory() -> Callable[[str], ContactProvider]:
    """Apollo comes before Hunter for users who saved an Apollo key (PLAN.md Phase 8)."""
    if get_settings().use_fakes:
        return lambda _key: FakeContactProvider(name="apollo", can_verify=False, resolve_names=False)
    return ApolloProvider


@lru_cache
def get_company_search() -> CompanySearchProvider:
    """Companies for open outreach: the public YC directory (Apollo's organization search needs a
    paid plan). USE_FAKES uses the recorded slice of it."""
    if get_settings().use_fakes:
        return FakeCompanySearch()
    return YCDirectory(get_source_http())


@lru_cache
def get_website_fetcher() -> WebsiteFetcher | None:
    """Reads a company's website on demand (open-outreach drafts with no company text yet). None with
    fakes on: tests and fake runs never fetch real sites."""
    if get_settings().use_fakes:
        return None
    return WebsiteFetcher(website_http())


_fake_mailboxes: dict[str, FakeGmailClient] = {}


def fake_mailbox(user_email: str) -> FakeGmailClient:
    return _fake_mailboxes.setdefault(user_email, FakeGmailClient(user_email))


async def _fake_gmail(_session: AsyncSession, user: User) -> GmailClient:
    return fake_mailbox(user.email)


def get_google_oauth() -> GoogleOAuth | None:
    """The real Google OAuth client when GOOGLE_CLIENT_ID/SECRET are set, otherwise None (sign in
    with dev-login). Independent of USE_FAKES so real sign-in can be tried against fake services."""
    settings = get_settings()
    if not (settings.google_client_id and settings.google_client_secret):
        return None
    return HttpGoogleOAuth(
        settings.google_client_id, settings.google_client_secret, settings.google_redirect_uri
    )


def get_gmail_factory() -> GmailFactory:
    """A function from (session, user) to that user's Gmail client. USE_FAKES gives an in-memory
    mailbox per user; otherwise their stored Google authorisation is used."""
    settings = get_settings()
    if settings.use_fakes:
        return _fake_gmail
    oauth = get_google_oauth()
    if oauth is None:
        raise RuntimeError("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are needed to send with Gmail")
    return GmailAccess(oauth, get_redis())


@lru_cache
def get_source_http() -> PoliteHttpClient:
    """Shared polite client (≤ 1 req/s per host) for job sources called from the API."""
    return PoliteHttpClient()
