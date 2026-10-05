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

from app.core.config import Settings, get_settings
from app.core.redis import get_redis
from app.services.contacts.base import ContactProvider
from app.services.contacts.fake import FakeContactProvider
from app.services.contacts.hunter import HunterProvider
from app.services.email.fake_gmail import FakeGmailClient
from app.services.email.gmail import GmailClient
from app.services.embeddings.bge import BgeEmbedder
from app.services.embeddings.embedder import Embedder
from app.services.embeddings.fake import FakeEmbedder
from app.services.llm.anthropic import AnthropicClient
from app.services.llm.cache import LLMCache
from app.services.llm.client import LLMClient
from app.services.llm.fake import FakeLLMClient
from app.services.llm.gemini import GeminiClient
from app.services.llm.rate_limit import RateLimiter
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


def build_fake_llm_client() -> FakeLLMClient:
    """For USE_FAKES=true local runs: canned answers so the UI works without an API key."""
    client = FakeLLMClient()
    for path in sorted(_FAKE_RESPONSES.glob("*.json")):
        client.add_response(path.stem, json.loads(path.read_text()))
    client.add_responder("match", _fake_match_scores)
    client.add_responder("tailor", _fake_tailor_plan)
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


_fake_mailboxes: dict[str, FakeGmailClient] = {}


def get_gmail_client(user_email: str) -> GmailClient:
    if get_settings().use_fakes:
        return _fake_mailboxes.setdefault(user_email, FakeGmailClient(user_email))
    raise NotImplementedError("real Gmail client arrives in Phase 7; set USE_FAKES=true")


@lru_cache
def get_source_http() -> PoliteHttpClient:
    """Shared polite client (≤ 1 req/s per host) for job sources called from the API."""
    return PoliteHttpClient()
