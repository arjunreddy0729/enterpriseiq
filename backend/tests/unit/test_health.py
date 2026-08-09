"""Health endpoint behaviour.

/healthz must not touch the database - that is the entire reason it is
separate from /readyz. These tests run with no PostgreSQL available.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_healthz_returns_healthy(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["app"] == "EnterpriseIQ"
    assert body["version"]


def test_healthz_does_not_require_a_database(client: TestClient) -> None:
    # Liveness must stay green even when Postgres is down, otherwise a brief
    # database blip triggers a restart storm across every replica.
    assert client.get("/healthz").status_code == 200


def test_every_response_carries_a_request_id(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.headers.get("X-Request-ID")


def test_supplied_request_id_is_echoed_back(client: TestClient) -> None:
    response = client.get("/healthz", headers={"X-Request-ID": "trace-me-123"})
    assert response.headers["X-Request-ID"] == "trace-me-123"


def test_root_advertises_the_health_endpoints(client: TestClient) -> None:
    body = client.get("/").json()
    assert body["health"] == {"liveness": "/healthz", "readiness": "/readyz"}


def test_openapi_schema_builds(client: TestClient) -> None:
    # Catches Pydantic models that cannot be serialised into a schema.
    schema = client.get("/openapi.json").json()
    assert "/healthz" in schema["paths"]
    assert "/readyz" in schema["paths"]


def test_unknown_route_uses_the_error_envelope(client: TestClient) -> None:
    response = client.get("/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "http_error"
    assert body["error"]["request_id"]
