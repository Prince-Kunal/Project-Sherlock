"""Picks real or fake implementations of every external service (PLAN.md §12, USE_FAKES).

Everything that talks to the outside world is obtained here, so tests and `USE_FAKES=true` swap
the whole app onto fakes without touching call sites.
"""

import json
from functools import lru_cache
from pathlib import Path

from app.core.config import Settings, get_settings
from app.core.redis import get_redis
from app.services.contacts.base import ContactProvider
from app.services.contacts.fake import FakeContactProvider
from app.services.email.fake_gmail import FakeGmailClient
from app.services.email.gmail import GmailClient
from app.services.embeddings.embedder import Embedder
from app.services.embeddings.fake import FakeEmbedder
from app.services.llm.anthropic import AnthropicClient
from app.services.llm.cache import LLMCache
from app.services.llm.client import LLMClient
from app.services.llm.fake import FakeLLMClient
from app.services.llm.gemini import GeminiClient
from app.services.llm.rate_limit import RateLimiter

_FAKE_RESPONSES = Path(__file__).parent / "llm" / "fake_responses"


def build_fake_llm_client() -> FakeLLMClient:
    """For USE_FAKES=true local runs: canned answers so the UI works without an API key."""
    client = FakeLLMClient()
    for path in sorted(_FAKE_RESPONSES.glob("*.json")):
        client.add_response(path.stem, json.loads(path.read_text()))
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
    if get_settings().use_fakes:
        return FakeEmbedder()
    raise NotImplementedError("real Embedder (bge-small) arrives in Phase 3; set USE_FAKES=true")


@lru_cache
def get_contact_provider() -> ContactProvider:
    if get_settings().use_fakes:
        return FakeContactProvider()
    raise NotImplementedError("Hunter ContactProvider arrives in Phase 5; set USE_FAKES=true")


_fake_mailboxes: dict[str, FakeGmailClient] = {}


def get_gmail_client(user_email: str) -> GmailClient:
    if get_settings().use_fakes:
        return _fake_mailboxes.setdefault(user_email, FakeGmailClient(user_email))
    raise NotImplementedError("real Gmail client arrives in Phase 7; set USE_FAKES=true")
