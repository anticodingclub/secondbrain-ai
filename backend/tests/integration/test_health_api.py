from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration

PREFIX = "/api/v1"


async def test_health_reports_ok(client: AsyncClient) -> None:
    response = await client.get(f"{PREFIX}/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["environment"] == "test"
    assert body["version"]


async def test_every_response_carries_a_correlation_id(client: AsyncClient) -> None:
    response = await client.get(f"{PREFIX}/health")
    assert response.headers["X-Request-ID"]


async def test_supplied_correlation_id_is_echoed_back(client: AsyncClient) -> None:
    response = await client.get(f"{PREFIX}/health", headers={"X-Request-ID": "trace-abc"})
    assert response.headers["X-Request-ID"] == "trace-abc"


async def test_readiness_checks_database_and_vector_store(client: AsyncClient) -> None:
    response = await client.get(f"{PREFIX}/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["dependencies"]["database"]["healthy"] is True
    assert body["dependencies"]["vector_store"]["healthy"] is True


async def test_system_endpoint_exposes_the_active_providers(client: AsyncClient) -> None:
    response = await client.get(f"{PREFIX}/system")

    assert response.status_code == 200
    body = response.json()
    assert body["vector_store"]["backend"] == "qdrant"
    assert body["vector_store"]["mode"] == "embedded"
    assert body["embedding"]["dimensions"] > 0


async def test_unknown_route_uses_the_shared_error_envelope(client: AsyncClient) -> None:
    response = await client.get(f"{PREFIX}/does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert body["error"] == "http_error"
    assert "request_id" in body
