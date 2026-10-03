from redis.asyncio import Redis

_PREFIX = "llm:cache:"


class LLMCache:
    """Redis cache of raw (already validated) LLM JSON, keyed by hash of prompt name + version + inputs."""

    def __init__(self, redis: Redis, ttl_seconds: int) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    async def get(self, key: str) -> str | None:
        value = await self._redis.get(_PREFIX + key)
        return value if isinstance(value, str) else None

    async def set(self, key: str, value: str) -> None:
        await self._redis.set(_PREFIX + key, value, ex=self._ttl)
