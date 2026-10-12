"""Structured logging, request ids, the API rate limit and env-gated Sentry (PLAN.md Phase 9)."""

import json
import logging
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.config import get_settings
from app.core.logging import (
    ContextFilter,
    JsonFormatter,
    TextFormatter,
    bind_log_context,
    current_log_context,
    log_context,
)
from app.core.sentry import _tag_with_context, init_sentry


def _record(msg: str = "hello %s", *args: object, **extra: object) -> logging.LogRecord:
    record = logging.makeLogRecord(
        {"name": "app.test", "levelname": "INFO", "msg": msg, "args": args or ("x",)}
    )
    record.__dict__.update(extra)
    ContextFilter().filter(record)
    return record


def test_json_lines_carry_the_context_and_extras() -> None:
    with log_context(request_id="r1", user_id="u1"):
        with log_context(outreach_id="o1"):
            line = json.loads(JsonFormatter().format(_record(status=200)))
        bind_log_context(match_id="m1", ignored=None)
        assert current_log_context() == {"request_id": "r1", "user_id": "u1", "match_id": "m1"}
    assert current_log_context() == {}
    assert line["msg"] == "hello x"
    assert (line["level"], line["logger"], line["status"]) == ("INFO", "app.test", 200)
    assert (line["request_id"], line["user_id"], line["outreach_id"]) == ("r1", "u1", "o1")


def test_json_lines_include_the_traceback() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.makeLogRecord({"msg": "failed", "exc_info": __import__("sys").exc_info()})
    ContextFilter().filter(record)
    assert "ValueError: boom" in json.loads(JsonFormatter().format(record))["exc"]


def test_text_lines_append_the_context() -> None:
    with log_context(user_id="u1"):
        assert TextFormatter().format(_record()).endswith("hello x [user_id=u1]")


async def test_requests_get_an_id_and_an_access_line_with_the_user(
    auth_client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    me = (await auth_client.get("/auth/me")).json()["id"]
    outreach_id = str(uuid.uuid4())
    with caplog.at_level(logging.INFO, logger="app.requests"):
        response = await auth_client.get(f"/outreach/{outreach_id}", headers={"X-Request-ID": "abc-123"})
    assert response.status_code == 404
    assert response.headers["x-request-id"] == "abc-123"
    [line] = [r for r in caplog.records if r.name == "app.requests" and outreach_id in r.getMessage()]
    assert line.getMessage().startswith(f"GET /outreach/{outreach_id} 404")
    assert line.context == {"request_id": "abc-123", "user_id": me, "outreach_id": outreach_id}  # type: ignore[attr-defined]

    generated = (await auth_client.get("/health", headers={"X-Request-ID": "bad id with spaces"})).headers
    assert len(generated["x-request-id"]) == 16


# --- Rate limit -------------------------------------------------------------------------------------


@pytest.fixture
def small_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "api_rate_burst", 3)
    monkeypatch.setattr(get_settings(), "api_rate_per_minute", 1)


@pytest.mark.usefixtures("small_bucket")
async def test_a_user_over_the_rate_limit_gets_429(
    auth_client: AsyncClient, other_user_headers: dict[str, str]
) -> None:
    codes = [(await auth_client.get("/preferences")).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    limited = await auth_client.get("/preferences")
    assert limited.json()["detail"]["code"] == "rate_limited"
    assert int(limited.headers["retry-after"]) > 0
    # Buckets are per user, and health checks are never limited.
    assert (await auth_client.get("/preferences", headers=other_user_headers)).status_code == 200
    assert [(await auth_client.get("/health")).status_code for _ in range(5)] == [200] * 5


@pytest.mark.usefixtures("small_bucket")
async def test_anonymous_requests_are_limited_per_ip(client: AsyncClient) -> None:
    one = {"X-Forwarded-For": "203.0.113.1"}
    codes = [(await client.get("/auth/config", headers=one)).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    assert (await client.get("/auth/config", headers={"X-Forwarded-For": "203.0.113.2"})).status_code == 200


@pytest.mark.usefixtures("small_bucket")
async def test_the_limit_can_be_switched_off_and_fails_open(
    auth_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "api_rate_limit_enabled", False)
    assert [(await auth_client.get("/preferences")).status_code for _ in range(5)] == [200] * 5
    monkeypatch.setattr(get_settings(), "api_rate_limit_enabled", True)

    class DownRedis:
        def register_script(self, _: str) -> Any:
            async def call(**_: object) -> int:
                raise RedisConnectionError("down")

            return call

    monkeypatch.setattr("app.api.middleware.get_redis", DownRedis)
    assert [(await auth_client.get("/preferences")).status_code for _ in range(5)] == [200] * 5


# --- Sentry -----------------------------------------------------------------------------------------


def test_sentry_only_starts_with_a_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    import sentry_sdk

    started: list[dict[str, Any]] = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: started.append(kw))
    assert init_sentry("api") is False
    assert started == []
    monkeypatch.setattr(get_settings(), "sentry_dsn", "https://key@sentry.example/1")
    assert init_sentry("worker") is True
    [options] = started
    assert options["send_default_pii"] is False
    assert options["server_name"] == "worker"
    with log_context(user_id="u1", outreach_id="o1"):
        event = _tag_with_context({"message": "x"}, None)
    assert event["tags"] == {"user_id": "u1", "outreach_id": "o1"}
