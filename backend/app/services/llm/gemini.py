"""Gemini implementation of LLMClient using the google-genai SDK (free tier first, PLAN.md §3.1)."""

import asyncio
import json
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.services.llm.cache import LLMCache
from app.services.llm.client import (
    LLMClient,
    LLMConfigError,
    LLMQuotaExhaustedError,
    LLMRateLimitedError,
    LLMRequest,
)
from app.services.llm.rate_limit import RateLimiter

log = logging.getLogger(__name__)

_RETRYABLE_SERVER_CODES = {500, 502, 503, 504}


def _is_daily_quota_error(err: genai_errors.APIError) -> bool:
    # Free-tier 429s carry QuotaFailure details whose quotaId names the window, e.g.
    # "GenerateRequestsPerDayPerProjectPerModel-FreeTier".
    return "PerDay" in json.dumps(err.details, default=str)


class GeminiClient(LLMClient):
    def __init__(
        self,
        *,
        default_api_key: str,
        model_smart: str,
        model_fast: str,
        limiter: RateLimiter,
        cache: LLMCache | None = None,
        max_retries: int = 4,
        base_delay_seconds: float = 2.0,
        max_delay_seconds: float = 60.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        super().__init__(cache)
        self._default_api_key = default_api_key
        self._models = {"smart": model_smart, "fast": model_fast}
        self._limiter = limiter
        self._max_retries = max_retries
        self._base_delay = base_delay_seconds
        self._max_delay = max_delay_seconds
        self._sleep = sleep

    async def _complete_json(self, request: LLMRequest, prompt: str, schema: dict[str, Any]) -> str:
        api_key = request.api_key or self._default_api_key
        if not api_key:
            raise LLMConfigError("no Gemini API key available (user key missing and no GEMINI_API_KEY)")
        model = self._models[request.tier]
        try:
            return await self._call_with_backoff(api_key, model, prompt, schema, request.prompt_name)
        except LLMRateLimitedError:
            if request.tier == "smart" and request.allow_fallback:
                log.warning("llm %s: %s rate-limited, falling back to fast model", request.prompt_name, model)
                return await self._call_with_backoff(
                    api_key, self._models["fast"], prompt, schema, request.prompt_name
                )
            raise

    async def _call_with_backoff(
        self, api_key: str, model: str, prompt: str, schema: dict[str, Any], prompt_name: str
    ) -> str:
        for attempt in range(self._max_retries + 1):
            await self._limiter.acquire(api_key)
            try:
                return await self._call(api_key, model, prompt, schema, prompt_name)
            except genai_errors.APIError as err:
                if err.code == 429 and _is_daily_quota_error(err):
                    await self._limiter.mark_exhausted(api_key)
                    raise LLMQuotaExhaustedError(f"Gemini daily quota exhausted for {model}") from err
                if err.code != 429 and err.code not in _RETRYABLE_SERVER_CODES:
                    raise
                if attempt == self._max_retries:
                    raise LLMRateLimitedError(f"{model}: still failing after {attempt + 1} attempts") from err
                delay = min(self._max_delay, self._base_delay * 2**attempt) * random.uniform(0.5, 1.5)
                log.info("llm %s: %s returned %s, retrying in %.1fs", prompt_name, model, err.code, delay)
                await self._sleep(delay)
        raise AssertionError("unreachable")

    async def _call(
        self, api_key: str, model: str, prompt: str, schema: dict[str, Any], prompt_name: str
    ) -> str:
        client = genai.Client(api_key=api_key)
        response = await client.aio.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_json_schema=schema,
                temperature=0.2,
            ),
        )
        if not response.text:
            # Empty (e.g. safety-blocked) output fails validation, so the caller's retry loop handles it.
            log.warning("llm %s: %s returned an empty response", prompt_name, model)
            return ""
        return response.text
