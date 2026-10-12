"""Per-request plumbing (PLAN.md Phase 9): a request id and log context for every request, one access
log line, and the API rate limit (a Redis token bucket per signed-in user, per client IP otherwise).

The limit protects the API (and, through it, everyone's LLM and Hunter quotas) from a stuck client
or a runaway script: `API_RATE_BURST` requests at once, refilled at `API_RATE_PER_MINUTE`. If Redis
is unreachable the request goes through; the limit is a safety net, not an invariant.
"""

import logging
import re
import time
import uuid

from fastapi import HTTPException, Request
from redis.exceptions import RedisError
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.auth import decode_session_token, token_from_request
from app.core.config import get_settings
from app.core.logging import bind_log_context, log_context
from app.core.rate_limit import BUCKET_LUA
from app.core.redis import get_redis

log = logging.getLogger("app.requests")

UNLIMITED_PATHS = frozenset({"/health", "/docs", "/redoc", "/openapi.json"})
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
# Path parameters worth having on every log line of a request.
_LOGGED_PATH_IDS = ("outreach_id", "match_id", "target_id")


def _client_key(request: Request) -> str:
    token = token_from_request(request)
    if token:
        try:
            return f"user:{decode_session_token(token)}"
        except HTTPException:
            pass
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")
    return f"ip:{ip}"


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def _retry_after(self, request: Request) -> int:
        """0 when the request may go ahead, else seconds until the client's bucket has a token."""
        settings = get_settings()
        if not settings.api_rate_limit_enabled or request.url.path in UNLIMITED_PATHS:
            return 0
        key = f"api:rate:{_client_key(request)}"
        try:
            bucket = get_redis().register_script(BUCKET_LUA)
            wait_ms = int(
                await bucket(
                    keys=[key],
                    args=[
                        settings.api_rate_burst,
                        settings.api_rate_per_minute / 60_000,
                        int(time.time() * 1000),
                        120_000,
                    ],
                )
            )
        except RedisError:
            log.warning("rate limit check skipped: redis unavailable", exc_info=True)
            return 0
        return 0 if wait_ms == 0 else max(1, -(-wait_ms // 1000))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        given = request.headers.get("x-request-id", "")
        request_id = given if _REQUEST_ID_RE.match(given) else uuid.uuid4().hex[:16]
        status_code = 500
        started = time.perf_counter()

        async def send_with_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                message.setdefault("headers", [])
                message["headers"] = [*message["headers"], (b"x-request-id", request_id.encode())]
            await send(message)

        with log_context(request_id=request_id):
            try:
                retry_after = await self._retry_after(request)
                if retry_after:
                    response = JSONResponse(
                        {
                            "detail": {
                                "code": "rate_limited",
                                "message": "Too many requests. Wait a few seconds and try again.",
                            }
                        },
                        status_code=429,
                        headers={"Retry-After": str(retry_after)},
                    )
                    await response(scope, receive, send_with_id)
                else:
                    await self.app(scope, receive, send_with_id)
            finally:
                path = request.url.path
                log.log(
                    logging.DEBUG if path in UNLIMITED_PATHS else logging.INFO,
                    "%s %s %d %.0fms",
                    request.method,
                    path,
                    status_code,
                    (time.perf_counter() - started) * 1000,
                    extra={"method": request.method, "path": path, "status": status_code},
                )


async def bind_path_ids(request: Request) -> None:
    """App-wide dependency: put the outreach/match/target id of the URL on the request's log lines."""
    bind_log_context(**{k: request.path_params.get(k) for k in _LOGGED_PATH_IDS})
