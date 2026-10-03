import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from fakeredis import FakeAsyncRedis
from pydantic import BaseModel, Field

from app.services.llm.cache import LLMCache
from app.services.llm.client import (
    LLMOutputError,
    LLMQuotaExhaustedError,
    LLMRateLimitedError,
    LLMRequest,
)
from app.services.llm.fake import FakeLLMClient
from app.services.llm.gemini import GeminiClient
from app.services.llm.prompt_loader import load_prompt, parse_prompt
from app.services.llm.rate_limit import RateLimiter
from app.services.llm.redaction import redact_pii, strip_basics


class Score(BaseModel):
    fit_score: int = Field(ge=0, le=100)
    reasoning: str


def _request(**overrides: Any) -> LLMRequest:
    defaults: dict[str, Any] = {"prompt_name": "match", "prompt_version": "1", "prompt": "Score this job."}
    return LLMRequest(**(defaults | overrides))


# --- validate-and-retry (invariant 7) ---


async def test_valid_output_is_parsed() -> None:
    llm = FakeLLMClient({"match": {"fit_score": 80, "reasoning": "Strong Python match."}})
    result = await llm.generate(_request(), Score)
    assert result == Score(fit_score=80, reasoning="Strong Python match.")
    assert len(llm.calls) == 1


async def test_invalid_output_retried_once_with_errors_in_prompt() -> None:
    llm = FakeLLMClient({"match": ['{"fit_score": 140}', '{"fit_score": 70, "reasoning": "ok"}']})
    result = await llm.generate(_request(), Score)
    assert result.fit_score == 70
    assert len(llm.calls) == 2
    retry_prompt = llm.calls[1][1]
    assert retry_prompt.startswith("Score this job.")
    assert "less than or equal to 100" in retry_prompt
    assert '{"fit_score": 140}' in retry_prompt


async def test_two_invalid_outputs_raise() -> None:
    llm = FakeLLMClient({"match": ["not json", "still not json"]})
    with pytest.raises(LLMOutputError):
        await llm.generate(_request(), Score)
    assert len(llm.calls) == 2


async def test_list_output_types_supported() -> None:
    llm = FakeLLMClient({"match": [[{"fit_score": 1, "reasoning": "a"}, {"fit_score": 2, "reasoning": "b"}]]})
    result = await llm.generate(_request(), list[Score])
    assert [s.fit_score for s in result] == [1, 2]


async def test_cache_hit_skips_the_model() -> None:
    cache = LLMCache(FakeAsyncRedis(decode_responses=True), ttl_seconds=60)
    llm = FakeLLMClient({"match": {"fit_score": 50, "reasoning": "x"}}, cache=cache)
    await llm.generate(_request(), Score)
    await llm.generate(_request(), Score)
    assert len(llm.calls) == 1
    # A different prompt version is a different cache entry.
    await llm.generate(_request(prompt_version="2"), Score)
    assert len(llm.calls) == 2


async def test_invalid_output_is_not_cached() -> None:
    redis = FakeAsyncRedis(decode_responses=True)
    llm = FakeLLMClient({"match": ["bad", "bad"]}, cache=LLMCache(redis, ttl_seconds=60))
    with pytest.raises(LLMOutputError):
        await llm.generate(_request(), Score)
    assert [k async for k in redis.scan_iter("llm:cache:*")] == []


# --- GeminiClient over mocked HTTP (invariant 8: no real API calls) ---

GEMINI_URL = r"https://generativelanguage\.googleapis\.com/.*/models/(?P<model>[^:]+):generateContent"


def _ok(payload: dict[str, Any]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "candidates": [
                {
                    "content": {"role": "model", "parts": [{"text": json.dumps(payload)}]},
                    "finishReason": "STOP",
                }
            ]
        },
    )


def _rate_limited(quota_id: str) -> httpx.Response:
    return httpx.Response(
        429,
        json={
            "error": {
                "code": 429,
                "message": "Resource has been exhausted",
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [{"quotaMetric": "generate_content_requests", "quotaId": quota_id}],
                    }
                ],
            }
        },
    )


PER_MINUTE = "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"
PER_DAY = "GenerateRequestsPerDayPerProjectPerModel-FreeTier"


class _NoSleep:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def _gemini(redis: FakeAsyncRedis, sleep: _NoSleep, *, rpd: int = 100, max_retries: int = 2) -> GeminiClient:
    return GeminiClient(
        default_api_key="owner-key",
        model_smart="smart-model",
        model_fast="fast-model",
        limiter=RateLimiter(redis, rpm=1000, rpd=rpd, sleep=sleep),
        max_retries=max_retries,
        sleep=sleep,
    )


@respx.mock
async def test_gemini_requests_json_with_schema_and_uses_user_key() -> None:
    route = respx.post(url__regex=GEMINI_URL).mock(return_value=_ok({"fit_score": 90, "reasoning": "r"}))
    client = _gemini(FakeAsyncRedis(decode_responses=True), _NoSleep())

    result = await client.generate(_request(tier="smart", api_key="user-key"), Score)

    assert result.fit_score == 90
    sent = route.calls.last.request
    assert "smart-model" in str(sent.url)
    assert sent.headers["x-goog-api-key"] == "user-key"
    body = json.loads(sent.content)
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["responseJsonSchema"]["required"] == ["fit_score", "reasoning"]


@respx.mock
async def test_gemini_backs_off_on_429_then_succeeds() -> None:
    respx.post(url__regex=GEMINI_URL).mock(
        side_effect=[_rate_limited(PER_MINUTE), _ok({"fit_score": 10, "reasoning": "r"})]
    )
    sleep = _NoSleep()
    client = _gemini(FakeAsyncRedis(decode_responses=True), sleep)
    result = await client.generate(_request(), Score)
    assert result.fit_score == 10
    assert len(sleep.delays) == 1
    assert sleep.delays[0] > 0


@respx.mock
async def test_gemini_gives_up_after_max_retries() -> None:
    respx.post(url__regex=GEMINI_URL).mock(return_value=_rate_limited(PER_MINUTE))
    client = _gemini(FakeAsyncRedis(decode_responses=True), _NoSleep(), max_retries=2)
    with pytest.raises(LLMRateLimitedError):
        await client.generate(_request(), Score)
    assert respx.calls.call_count == 3


@respx.mock
async def test_gemini_daily_quota_raises_and_blocks_further_calls() -> None:
    respx.post(url__regex=GEMINI_URL).mock(return_value=_rate_limited(PER_DAY))
    redis = FakeAsyncRedis(decode_responses=True)
    client = _gemini(redis, _NoSleep())
    with pytest.raises(LLMQuotaExhaustedError):
        await client.generate(_request(), Score)
    # Subsequent calls fail fast without hitting the API.
    with pytest.raises(LLMQuotaExhaustedError):
        await client.generate(_request(prompt="another"), Score)
    assert respx.calls.call_count == 1


@respx.mock
async def test_smart_model_falls_back_to_fast_once_when_allowed() -> None:
    def respond(request: httpx.Request, model: str) -> httpx.Response:
        if model == "smart-model":
            return _rate_limited(PER_MINUTE)
        return _ok({"fit_score": 33, "reasoning": "fast"})

    respx.post(url__regex=GEMINI_URL).mock(side_effect=respond)
    client = _gemini(FakeAsyncRedis(decode_responses=True), _NoSleep(), max_retries=1)
    result = await client.generate(_request(tier="smart", allow_fallback=True), Score)
    assert result.reasoning == "fast"

    with pytest.raises(LLMRateLimitedError):
        await client.generate(_request(tier="smart", allow_fallback=False, prompt="other"), Score)


@respx.mock
async def test_gemini_invalid_json_goes_through_validation_retry() -> None:
    respx.post(url__regex=GEMINI_URL).mock(
        side_effect=[_ok({"fit_score": "high"}), _ok({"fit_score": 60, "reasoning": "fixed"})]
    )
    client = _gemini(FakeAsyncRedis(decode_responses=True), _NoSleep())
    result = await client.generate(_request(), Score)
    assert result.reasoning == "fixed"


# --- Rate limiter ---


class _Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


async def test_token_bucket_waits_when_rpm_exhausted() -> None:
    clock = _Clock()

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock.now += seconds

    sleeps: list[float] = []
    limiter = RateLimiter(FakeAsyncRedis(decode_responses=True), rpm=2, rpd=100, clock=clock, sleep=sleep)
    await limiter.acquire("k")
    await limiter.acquire("k")
    assert sleeps == []
    await limiter.acquire("k")  # bucket empty: must wait ~30s for one token at 2/min
    assert 29 <= sum(sleeps) <= 31


async def test_rate_limits_are_per_key() -> None:
    clock = _Clock()
    limiter = RateLimiter(FakeAsyncRedis(decode_responses=True), rpm=1, rpd=1, clock=clock)
    await limiter.acquire("user-a")
    await limiter.acquire("user-b")
    with pytest.raises(LLMQuotaExhaustedError):
        await limiter.acquire("user-a")


async def test_daily_limit_resets_on_next_pacific_day() -> None:
    clock = _Clock()
    limiter = RateLimiter(FakeAsyncRedis(decode_responses=True), rpm=100, rpd=1, clock=clock)
    await limiter.acquire("k")
    with pytest.raises(LLMQuotaExhaustedError):
        await limiter.acquire("k")
    clock.now += 24 * 3600
    await limiter.acquire("k")


async def test_raw_api_key_never_stored_in_redis() -> None:
    redis = FakeAsyncRedis(decode_responses=True)
    limiter = RateLimiter(redis, rpm=10, rpd=10)
    await limiter.acquire("AIzaSecretKey123")
    keys = [k async for k in redis.scan_iter()]
    assert keys
    assert not any("AIzaSecretKey123" in k for k in keys)


# --- PII redaction ---


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Mail me at jane.doe+jobs@gmail.com today", "Mail me at [email] today"),
        ("Call +91 98765 43210 now", "Call [phone] now"),
        ("US: (415) 555-0100.", "US: [phone]."),
        (
            "Improved latency by 30% across 12 services in 2024",
            "Improved latency by 30% across 12 services in 2024",
        ),
    ],
)
def test_redact_pii(text: str, expected: str) -> None:
    assert redact_pii(text) == expected


def test_strip_basics_removes_contact_block_without_mutating() -> None:
    resume = {"basics": {"name": "Jane", "email": "j@x.com"}, "summary": "Engineer", "skills": {}}
    stripped = strip_basics(resume)
    assert "basics" not in stripped
    assert stripped["summary"] == "Engineer"
    assert "basics" in resume


# --- Prompt loader ---


def test_prompt_render_and_request(tmp_path: Path) -> None:
    (tmp_path / "match.md").write_text("---\nversion: 3\n---\nRoles: {{roles}}\nJob: {{ job }}\n")
    prompt = load_prompt("match", tmp_path)
    request = prompt.request(tier="fast", roles=["backend", "ml"], job="Intern")
    assert request.prompt_version == "3"
    assert '"backend"' in request.prompt
    assert "Job: Intern" in request.prompt


def test_prompt_render_rejects_missing_and_unused_variables() -> None:
    prompt = parse_prompt("p", "---\nversion: 1\n---\nHello {{name}}\n")
    with pytest.raises(ValueError, match="missing"):
        prompt.render()
    with pytest.raises(ValueError, match="unused"):
        prompt.render(name="x", extra="y")


def test_prompt_requires_version() -> None:
    with pytest.raises(ValueError, match="version"):
        parse_prompt("p", "---\nowner: me\n---\nbody\n")
