"""A polite HTTP client for job sources: ≤ 1 request per second per host, retries with backoff.

The per-host spacing is in-process (one worker process polls). If several workers ever poll at once,
move the spacing to Redis.
"""

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse

import httpx

log = logging.getLogger(__name__)

USER_AGENT = "Sherlock/0.1 (self-hosted job discovery for a small group of students)"
_RETRY_STATUSES = {429, 500, 502, 503, 504}


class SourceHTTPError(Exception):
    def __init__(self, url: str, status: int | None, message: str) -> None:
        super().__init__(f"{url}: {message}")
        self.url = url
        self.status = status


class PoliteHttpClient:
    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        min_interval_seconds: float = 1.0,
        max_retries: int = 3,
        base_delay_seconds: float = 1.0,
        timeout_seconds: float = 20.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client or httpx.AsyncClient(
            timeout=timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )
        self._min_interval = min_interval_seconds
        self._max_retries = max_retries
        self._base_delay = base_delay_seconds
        self._sleep = sleep
        self._clock = clock
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_request: dict[str, float] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _spaced(self, host: str, send: Callable[[], Awaitable[httpx.Response]]) -> httpx.Response:
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            wait = self._last_request.get(host, float("-inf")) + self._min_interval - self._clock()
            if wait > 0:
                await self._sleep(wait)
            try:
                return await send()
            finally:
                self._last_request[host] = self._clock()

    async def get(
        self, url: str, *, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None
    ) -> httpx.Response:
        host = urlparse(url).hostname or url
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._spaced(
                    host, lambda: self._client.get(url, params=params, headers=headers)
                )
            except httpx.TransportError as exc:
                if attempt == self._max_retries:
                    raise SourceHTTPError(url, None, f"network error: {type(exc).__name__}") from exc
                await self._backoff(attempt, None)
                continue
            if response.status_code in _RETRY_STATUSES and attempt < self._max_retries:
                await self._backoff(attempt, response.headers.get("Retry-After"))
                continue
            if response.status_code >= 400:
                raise SourceHTTPError(url, response.status_code, f"HTTP {response.status_code}")
            return response
        raise AssertionError("unreachable")

    async def get_json(self, url: str, *, params: dict[str, Any] | None = None) -> Any:
        response = await self.get(url, params=params, headers={"Accept": "application/json"})
        try:
            return response.json()
        except ValueError as exc:
            raise SourceHTTPError(url, response.status_code, "response is not JSON") from exc

    async def _backoff(self, attempt: int, retry_after: str | None) -> None:
        delay = self._base_delay * 2**attempt * random.uniform(0.75, 1.25)
        if retry_after and retry_after.isdigit():
            delay = max(delay, min(float(retry_after), 60.0))
        log.info("http retry %d in %.1fs", attempt + 1, delay)
        await self._sleep(delay)
