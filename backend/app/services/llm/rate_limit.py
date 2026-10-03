"""Per-API-key rate limiting in Redis: a token bucket for requests/minute plus a daily counter.

Gemini's free-tier daily quota resets at midnight US Pacific time, so the daily window uses that date.
Keys are identified by a hash; the raw API key never touches Redis.
"""

import asyncio
import hashlib
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from redis.asyncio import Redis

from app.services.llm.client import LLMQuotaExhaustedError, LLMRateLimitedError

_PACIFIC = ZoneInfo("America/Los_Angeles")
_DAY_TTL_SECONDS = 36 * 3600

# Returns 0 if a token was taken, otherwise the milliseconds until one is available.
_BUCKET_LUA = """
local capacity = tonumber(ARGV[1])
local refill_per_ms = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])
local state = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(state[1]) or capacity
local ts = tonumber(state[2]) or now
tokens = math.min(capacity, tokens + math.max(0, now - ts) * refill_per_ms)
local wait = 0
if tokens >= 1 then
  tokens = tokens - 1
else
  wait = math.ceil((1 - tokens) / refill_per_ms)
end
redis.call('HSET', KEYS[1], 'tokens', tostring(tokens), 'ts', tostring(now))
redis.call('PEXPIRE', KEYS[1], ttl)
return wait
"""


def key_fingerprint(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()[:16]


class RateLimiter:
    def __init__(
        self,
        redis: Redis,
        *,
        rpm: int,
        rpd: int,
        max_wait_seconds: float = 120.0,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._redis = redis
        self._rpm = rpm
        self._rpd = rpd
        self._max_wait = max_wait_seconds
        self._clock = clock
        self._sleep = sleep
        self._bucket = redis.register_script(_BUCKET_LUA)

    def _day_key(self, fingerprint: str) -> str:
        day = datetime.fromtimestamp(self._clock(), _PACIFIC).date().isoformat()
        return f"llm:rpd:{fingerprint}:{day}"

    async def acquire(self, api_key: str) -> None:
        """Block until a request may be made with this key. Raises if the daily quota is used up."""
        fingerprint = key_fingerprint(api_key)
        day_key = self._day_key(fingerprint)
        used = await self._redis.incr(day_key)
        if used == 1:
            await self._redis.expire(day_key, _DAY_TTL_SECONDS)
        if used > self._rpd:
            raise LLMQuotaExhaustedError(f"daily request limit ({self._rpd}) reached for key {fingerprint}")

        waited = 0.0
        refill_per_ms = self._rpm / 60_000
        while True:
            now_ms = int(self._clock() * 1000)
            wait_ms = int(
                await self._bucket(
                    keys=[f"llm:rpm:{fingerprint}"], args=[self._rpm, refill_per_ms, now_ms, 120_000]
                )
            )
            if wait_ms == 0:
                return
            if waited + wait_ms / 1000 > self._max_wait:
                raise LLMRateLimitedError(f"per-minute limit for key {fingerprint}: would wait too long")
            await self._sleep(wait_ms / 1000)
            waited += wait_ms / 1000

    async def mark_exhausted(self, api_key: str) -> None:
        """The provider reported the daily quota is gone: make further acquires fail fast until reset."""
        day_key = self._day_key(key_fingerprint(api_key))
        await self._redis.set(day_key, self._rpd, ex=_DAY_TTL_SECONDS)
