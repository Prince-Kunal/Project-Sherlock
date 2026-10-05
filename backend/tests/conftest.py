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
        "ALLOW_OWNER_KEY_FALLBACK": "false",
    }
)

import json
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import create_session_token
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.redis import get_redis
from app.models import Base, User
from app.services.contacts.fake import FakeContactProvider
from app.services.llm.fake import FakeLLMClient
from app.services.registry import get_contact_provider_factory, get_llm_client

BACKEND_DIR = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"


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


@pytest.fixture(autouse=True)
def storage_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path / "files"))
    return tmp_path / "files"


def recorded(prompt: str, name: str) -> object:
    """A recorded real LLM response from tests/fixtures/llm/<prompt>/<name>.json."""
    return json.loads((FIXTURES / "llm" / prompt / f"{name}.json").read_text())


@pytest.fixture
def fake_llm() -> Iterator[FakeLLMClient]:
    """Injected in place of the real LLM client for every request made through `client`."""
    from app.main import app

    fake = FakeLLMClient(rejected_keys={"AIza-rejected-key-000"})
    app.dependency_overrides[get_llm_client] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_llm_client, None)


@pytest.fixture
async def auth_client(client: AsyncClient) -> AsyncClient:
    """`client` logged in as the seeded dev user."""
    response = await client.post("/auth/dev-login")
    assert response.status_code == 200
    return client


@pytest.fixture
async def with_llm_key(auth_client: AsyncClient, fake_llm: FakeLLMClient) -> AsyncClient:
    """Logged-in client whose user has saved a (fake-verified) Gemini key."""
    response = await auth_client.put("/settings/llm-key", json={"api_key": "AIza-test-key-1234567890"})
    assert response.status_code == 200, response.text
    return auth_client


@pytest.fixture
async def other_user_headers(session: AsyncSession) -> dict[str, str]:
    """Auth headers for a second, unrelated user (data-isolation tests, invariant 5)."""
    user = User(email="other@example.com", name="Other User")
    session.add(user)
    await session.commit()
    return {"Authorization": f"Bearer {create_session_token(user.id)}"}


@pytest.fixture
def fake_contacts() -> Iterator[FakeContactProvider]:
    """A fresh fake Hunter for every request made through `client` (keys starting "rejected" fail)."""
    from app.main import app

    fake = FakeContactProvider()

    def factory(key: str) -> FakeContactProvider:
        fake.rejected = key.startswith("rejected")
        return fake

    app.dependency_overrides[get_contact_provider_factory] = lambda: factory
    yield fake
    app.dependency_overrides.pop(get_contact_provider_factory, None)


@pytest.fixture
async def with_hunter_key(auth_client: AsyncClient, fake_contacts: FakeContactProvider) -> AsyncClient:
    """Logged-in client whose user has saved a (fake-verified) Hunter key."""
    response = await auth_client.put("/settings/hunter-key", json={"api_key": "hunter-test-key-123"})
    assert response.status_code == 200, response.text
    fake_contacts.calls.clear()
    return auth_client
