"""Provider-agnostic LLM interface (PLAN.md §3.1, invariant 7).

Every call returns a validated Pydantic object. Invalid output is retried once with the validation
error appended to the prompt; a second failure raises `LLMOutputError`. Raw LLM text never leaves
this module unvalidated.
"""

import hashlib
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import TypeAdapter, ValidationError

from app.services.llm.cache import LLMCache

log = logging.getLogger(__name__)

ModelTier = Literal["smart", "fast"]


class LLMError(Exception):
    """Base class for LLM failures callers may want to handle."""


class LLMOutputError(LLMError):
    """The model returned output that failed validation twice."""

    def __init__(self, prompt_name: str, errors: str) -> None:
        super().__init__(f"{prompt_name}: invalid LLM output after retry: {errors}")
        self.prompt_name = prompt_name
        self.errors = errors


class LLMRateLimitedError(LLMError):
    """Per-minute limit still hit after all backoff retries."""


class LLMQuotaExhaustedError(LLMError):
    """The key's daily quota is used up. Callers should defer remaining work to the next day."""


class LLMConfigError(LLMError):
    """Missing API key or similar misconfiguration."""


@dataclass(frozen=True)
class LLMRequest:
    prompt_name: str
    prompt_version: str
    prompt: str  # fully rendered, already PII-redacted (see redaction.py)
    tier: ModelTier = "fast"
    api_key: str | None = None  # the user's own key (BYOK); None means the owner's key
    allow_fallback: bool = False  # smart tier may fall back to fast once when rate-limited
    use_cache: bool = True


_RETRY_SUFFIX = """

---
Your previous response was not valid. Validation errors:
{errors}

Previous response:
{previous}

Respond again with JSON only, matching the schema exactly."""


class LLMClient(ABC):
    def __init__(self, cache: LLMCache | None = None) -> None:
        self._cache = cache

    async def generate[T](self, request: LLMRequest, output_type: type[T]) -> T:
        adapter: TypeAdapter[T] = TypeAdapter(output_type)
        schema = adapter.json_schema()
        cache_key = _cache_key(request, schema)

        if self._cache is not None and request.use_cache:
            cached = await self._cache.get(cache_key)
            if cached is not None:
                try:
                    return adapter.validate_json(cached)
                except ValidationError:
                    log.warning("llm cache entry for %s failed validation; ignoring", request.prompt_name)

        prompt = request.prompt
        errors = ""
        for attempt in (1, 2):
            raw = await self._complete_json(request, prompt, schema)
            try:
                result = adapter.validate_json(raw)
            except ValidationError as exc:
                errors = exc.json(include_url=False, include_context=False)
                log.info("llm %s attempt %d failed validation", request.prompt_name, attempt)
                prompt = request.prompt + _RETRY_SUFFIX.format(errors=errors, previous=raw[:4000])
                continue
            if self._cache is not None and request.use_cache:
                await self._cache.set(cache_key, raw)
            return result
        raise LLMOutputError(request.prompt_name, errors)

    @abstractmethod
    async def _complete_json(self, request: LLMRequest, prompt: str, schema: dict[str, Any]) -> str:
        """Return the model's raw JSON text for `prompt`, constrained to `schema` where supported."""


def _cache_key(request: LLMRequest, schema: dict[str, Any]) -> str:
    material = json.dumps(
        [request.prompt_name, request.prompt_version, request.tier, request.prompt, schema],
        sort_keys=True,
    )
    return hashlib.sha256(material.encode()).hexdigest()
