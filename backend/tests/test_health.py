from httpx import AsyncClient


async def test_health_reports_db_and_redis_ok(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok", "redis": "ok"}


async def test_health_is_public(client: AsyncClient) -> None:
    # No session needed: load balancers and docker healthchecks call it.
    response = await client.get("/health")
    assert response.status_code == 200
