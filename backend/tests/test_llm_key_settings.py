from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decrypt_secret
from app.models import UserLLMKey
from app.services.llm.fake import FakeLLMClient

KEY = "AIza-test-key-1234567890"


async def test_status_before_key_shows_notice(auth_client: AsyncClient) -> None:
    body = (await auth_client.get("/settings/llm-key")).json()
    assert body["configured"] is False
    assert body["owner_fallback_allowed"] is False
    assert "human reviewers" in body["notice"]


async def test_valid_key_is_verified_then_stored_encrypted(
    auth_client: AsyncClient, fake_llm: FakeLLMClient, session: AsyncSession
) -> None:
    response = await auth_client.put("/settings/llm-key", json={"api_key": f"  {KEY}  "})
    assert response.status_code == 200
    assert response.json()["configured"] is True
    assert response.json()["verified_at"] is not None
    assert "api_key" not in response.json()

    # Exactly one tiny verification request, made with the new key.
    assert [(r.prompt_name, r.api_key) for r, _ in fake_llm.calls] == [("verify_key", KEY)]

    row = (await session.execute(select(UserLLMKey))).scalar_one()
    assert KEY not in row.encrypted_api_key  # invariant 6
    assert decrypt_secret(row.encrypted_api_key) == KEY


async def test_rejected_key_is_not_stored(
    auth_client: AsyncClient, fake_llm: FakeLLMClient, session: AsyncSession
) -> None:
    response = await auth_client.put("/settings/llm-key", json={"api_key": "AIza-rejected-key-000"})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "llm_key_invalid"
    assert (await session.execute(select(UserLLMKey))).scalar_one_or_none() is None


async def test_replacing_and_deleting_key(
    auth_client: AsyncClient, fake_llm: FakeLLMClient, session: AsyncSession
) -> None:
    await auth_client.put("/settings/llm-key", json={"api_key": KEY})
    await auth_client.put("/settings/llm-key", json={"api_key": "AIza-second-key-0987654321"})
    rows = (await session.execute(select(UserLLMKey))).scalars().all()
    assert len(rows) == 1
    assert decrypt_secret(rows[0].encrypted_api_key) == "AIza-second-key-0987654321"

    assert (await auth_client.delete("/settings/llm-key")).status_code == 204
    assert (await auth_client.get("/settings/llm-key")).json()["configured"] is False


async def test_key_status_is_per_user(
    auth_client: AsyncClient, fake_llm: FakeLLMClient, other_user_headers: dict[str, str]
) -> None:
    await auth_client.put("/settings/llm-key", json={"api_key": KEY})
    auth_client.cookies.clear()
    other = (await auth_client.get("/settings/llm-key", headers=other_user_headers)).json()
    assert other["configured"] is False
