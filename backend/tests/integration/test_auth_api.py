"""Login and token handling through the real HTTP stack."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from tests.integration.conftest import login, requires_corpus

pytestmark = [pytest.mark.integration, requires_corpus]

ENGINEER = "priya.raman@northwind.example"
ADMIN = "admin@northwind.example"


@pytest.fixture
def no_dev_header() -> Iterator[None]:
    """Run with AUTH_DEV_HEADER_ENABLED=false, as production does."""
    strict = get_settings().model_copy(update={"auth_dev_header_enabled": False})
    app.dependency_overrides[get_settings] = lambda: strict
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_settings, None)


def test_login_returns_a_bearer_token(client: TestClient) -> None:
    password = get_settings().demo_user_password
    assert password is not None
    response = client.post(
        "/api/v1/auth/token",
        json={"email": ENGINEER, "password": password.get_secret_value()},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == get_settings().access_token_ttl_minutes * 60


def test_wrong_password_and_unknown_user_look_identical(client: TestClient) -> None:
    """Same status and same message, so the endpoint cannot be used to find
    out which emails have accounts."""
    wrong = client.post(
        "/api/v1/auth/token", json={"email": ENGINEER, "password": "not-the-password"}
    )
    unknown = client.post(
        "/api/v1/auth/token", json={"email": "nobody@northwind.example", "password": "x"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]
    assert wrong.headers["WWW-Authenticate"] == "Bearer"


def test_bearer_token_authenticates_search(client: TestClient) -> None:
    response = client.post(
        "/api/v1/search", json={"query": "deployment rollback"}, headers=login(client, ENGINEER)
    )
    assert response.status_code == 200
    assert response.json()["identity"]["email"] == ENGINEER


def test_me_reports_current_groups(client: TestClient) -> None:
    body = client.get("/api/v1/auth/me", headers=login(client, ENGINEER)).json()
    assert body["email"] == ENGINEER
    assert set(body["groups"]) == {"engineering", "all-employees"}


@pytest.mark.parametrize("token", ["garbage", "a.b.c", ""])
def test_invalid_bearer_token_is_401(client: TestClient, token: str) -> None:
    response = client.post(
        "/api/v1/search",
        json={"query": "x"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401


def test_bearer_token_wins_over_the_dev_header(client: TestClient) -> None:
    """An engineer's token plus a claimed admin dev header is still the engineer."""
    headers = {**login(client, ENGINEER), "X-Dev-User": ADMIN}
    body = client.get("/api/v1/auth/me", headers=headers).json()
    assert body["email"] == ENGINEER


def test_dev_header_is_ignored_when_disabled(client: TestClient, no_dev_header: None) -> None:
    response = client.post("/api/v1/search", json={"query": "x"}, headers={"X-Dev-User": ADMIN})
    assert response.status_code == 401


def test_tokens_still_work_when_the_dev_header_is_disabled(
    client: TestClient, no_dev_header: None
) -> None:
    response = client.get("/api/v1/auth/me", headers=login(client, ENGINEER))
    assert response.status_code == 200


def test_admin_endpoints_reject_non_admins(client: TestClient) -> None:
    response = client.get("/api/v1/admin/documents", headers=login(client, ENGINEER))
    assert response.status_code == 403


def test_admin_endpoints_reject_anonymous_callers(client: TestClient) -> None:
    assert client.get("/api/v1/admin/documents").status_code == 401
