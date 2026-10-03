"""Test setup. Tests run against real Postgres + Redis (docker compose, or CI service containers)
on a dedicated database, with every external API replaced by fakes (invariant 8)."""

import os

# Must be set before any app module reads settings.
os.environ.update(
    {
        "ENV": "test",
        "DATABASE_URL": os.environ.get(
            "TEST_DATABASE_URL", "postgresql+asyncpg://sherlock:sherlock@localhost:5433/sherlock_test"
        ),
        "REDIS_URL": os.environ.get("TEST_REDIS_URL", "redis://localhost:6380/15"),
        "AUTH_SECRET": "test-secret-not-for-production-use-0123456789",
        "FERNET_KEY": "Gr6V6l1M0r2Vq3pkzW3dQx7X3WZb0Yb2fN1g4wqJ0zA=",
        "DEV_AUTH": "true",
        "USE_FAKES": "true",
        "GEMINI_API_KEY": "",
    }
)

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.redis import get_redis
from app.models import Base

BACKEND_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session", autouse=True)
def _migrated_database() -> None:
    """Rebuild the test schema from migrations once per run, so migrations themselves are tested."""
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["database_url"] = get_settings().database_url
    command.downgrade(config, "base")
    command.upgrade(config, "head")


@pytest.fixture(autouse=True)
async def _clean_state() -> AsyncIterator[None]:
    yield
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    async with get_sessionmaker()() as session:
        await session.execute(text(f"TRUNCATE {tables} CASCADE"))
        await session.commit()
    await get_redis().flushdb()


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as s:
        yield s


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from app.main import app

    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        yield c
