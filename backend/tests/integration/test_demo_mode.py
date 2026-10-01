"""The public-demo protections, against the real app and database.

The app is built fresh with DEMO_MODE=true for each test, because some of
what demo mode changes (the landing page at /) is decided when the app is
created, not per request.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.errors import BudgetExhaustedError
from app.core.config import get_settings
from app.core.identity import resolve_identity
from app.core.rate_limit import limiter
from app.db.models import Document
from app.db.session import SessionLocal
from app.generation.llm import StubLLMClient
from app.main import create_app
from app.retrieval.embedder import get_embedder
from app.services.query_service import QueryService
from tests.integration.conftest import login, requires_corpus

pytestmark = [pytest.mark.integration, requires_corpus]

HR_PERSON = "marcus.webb@northwind.example"
ENGINEER = "priya.raman@northwind.example"
ADMIN = "admin@northwind.example"
COMP_POLICY = "hr/compensation-policy.md"


@pytest.fixture
def demo_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "1000")
    monkeypatch.setenv("RATE_LIMIT_LOGIN_PER_MINUTE", "50")
    monkeypatch.setenv("RATE_LIMIT_SEARCH_PER_MINUTE", "50")
    get_settings.cache_clear()
    limiter.reset()
    try:
        yield
    finally:
        limiter.reset()
        get_settings.cache_clear()


@pytest.fixture
def demo(demo_env: None) -> Iterator[TestClient]:
    with TestClient(create_app()) as client:
        yield client


@pytest.fixture
def session() -> Iterator[Session]:
    with SessionLocal() as s:
        yield s


def comp_policy_id(session: Session) -> str:
    return str(
        session.execute(select(Document.id).where(Document.source_uri == COMP_POLICY)).scalar_one()
    )


# ---------------------------------------------------------------------------
# Landing page and login
# ---------------------------------------------------------------------------
def test_landing_page_shows_demo_logins(demo: TestClient) -> None:
    response = demo.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    password = get_settings().demo_user_password
    assert password is not None
    assert password.get_secret_value() in response.text
    assert 'href="/docs"' in response.text
    assert HR_PERSON in response.text


def test_root_is_json_outside_demo_mode(client: TestClient) -> None:
    assert client.get("/").json()["docs"] == "/docs"


def test_authorize_button_login_works(demo: TestClient) -> None:
    """The form-encoded endpoint the /docs Authorize dialog calls."""
    password = get_settings().demo_user_password
    assert password is not None
    response = demo.post(
        "/api/v1/auth/login",
        data={"username": HR_PERSON, "password": password.get_secret_value()},
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    me = demo.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["email"] == HR_PERSON


def test_dev_header_is_still_accepted_only_where_configured(demo: TestClient) -> None:
    """Demo mode does not by itself switch off the dev header; production
    settings do (the deploy image sets AUTH_DEV_HEADER_ENABLED=false)."""
    response = demo.get("/api/v1/auth/me", headers={"X-Dev-User": ENGINEER})
    assert response.status_code == (200 if get_settings().auth_dev_header_enabled else 401)


# ---------------------------------------------------------------------------
# Rate limits
# ---------------------------------------------------------------------------
def test_login_is_rate_limited(monkeypatch: pytest.MonkeyPatch, demo_env: None) -> None:
    monkeypatch.setenv("RATE_LIMIT_LOGIN_PER_MINUTE", "3")
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        codes = [
            client.post(
                "/api/v1/auth/token", json={"email": HR_PERSON, "password": "wrong"}
            ).status_code
            for _ in range(4)
        ]
        assert codes == [401, 401, 401, 429]
        blocked = client.post("/api/v1/auth/token", json={"email": HR_PERSON, "password": "x"})
        assert int(blocked.headers["Retry-After"]) > 0


def test_search_is_rate_limited(monkeypatch: pytest.MonkeyPatch, demo_env: None) -> None:
    monkeypatch.setenv("RATE_LIMIT_SEARCH_PER_MINUTE", "2")
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        headers = login(client, ENGINEER)
        codes = [
            client.post("/api/v1/search", json={"query": "rollback"}, headers=headers).status_code
            for _ in range(3)
        ]
        assert codes == [200, 200, 429]


def test_rate_limits_are_off_outside_demo_mode(client: TestClient) -> None:
    limiter.reset()
    codes = {
        client.post("/api/v1/auth/token", json={"email": HR_PERSON, "password": "x"}).status_code
        for _ in range(15)
    }
    assert codes == {401}


# ---------------------------------------------------------------------------
# Read-only admin, hidden queries
# ---------------------------------------------------------------------------
def test_admin_can_read_but_not_change_permissions(demo: TestClient, session: Session) -> None:
    admin = login(demo, ADMIN)
    url = f"/api/v1/admin/documents/{comp_policy_id(session)}/permissions"

    assert demo.get(url, headers=admin).status_code == 200
    response = demo.put(url, json={"groups": ["legal"]}, headers=admin)
    assert response.status_code == 403
    assert "disabled in the public demo" in response.json()["error"]["message"]
    assert demo.get(url, headers=admin).json()["groups"] == ["hr"]


def test_audit_hides_what_visitors_typed(demo: TestClient, session: Session) -> None:
    secret_question = "bonus targets by level for my private salary review"
    demo.post("/api/v1/search", json={"query": secret_question}, headers=login(demo, HR_PERSON))
    report = demo.get(
        f"/api/v1/admin/audit/documents/{comp_policy_id(session)}",
        params={"days": 1},
        headers=login(demo, ADMIN),
    ).json()
    assert report["events"], "the search should appear in the audit trail"
    assert all(e["query"] == "[hidden in the public demo]" for e in report["events"])
    assert secret_question not in str(report)


# ---------------------------------------------------------------------------
# Daily spend cap
# ---------------------------------------------------------------------------
def test_spent_budget_stops_model_calls(
    session: Session, monkeypatch: pytest.MonkeyPatch, demo_env: None
) -> None:
    monkeypatch.setattr(get_settings(), "llm_daily_budget_usd", 0.0)
    stub = StubLLMClient("Answer [1].")
    service = QueryService(session, get_embedder(), stub)

    with pytest.raises(BudgetExhaustedError):
        service.answer("What are the bonus targets by level?", resolve_identity(session, HR_PERSON))
    assert stub.calls == []


def test_questions_declined_for_free_never_hit_the_budget(
    session: Session, monkeypatch: pytest.MonkeyPatch, demo_env: None
) -> None:
    """The relevance gate runs first, so an exhausted budget does not turn a
    normal 'no information' answer into an error."""
    monkeypatch.setattr(get_settings(), "llm_daily_budget_usd", 0.0)
    outcome = QueryService(session, get_embedder(), StubLLMClient()).answer(
        "What are the bonus targets by level?", resolve_identity(session, ENGINEER)
    )
    assert outcome.status == "insufficient_evidence"


def test_under_budget_answers_normally(
    session: Session, monkeypatch: pytest.MonkeyPatch, demo_env: None
) -> None:
    monkeypatch.setattr(get_settings(), "llm_daily_budget_usd", 1000.0)
    stub = StubLLMClient("Answer [1].")
    QueryService(session, get_embedder(), stub).answer(
        "What are the bonus targets by level?", resolve_identity(session, HR_PERSON)
    )
    assert len(stub.calls) == 1


def test_spend_is_read_from_the_request_log(session: Session) -> None:
    """Spend survives restarts because it is summed from query_logs."""
    from decimal import Decimal

    from app.db.models import QueryLog

    service = QueryService(session, get_embedder(), StubLLMClient())
    before = service.spent_today_usd()
    row = QueryLog(
        request_id="budget-test",
        endpoint="query",
        query="x",
        status="answered",
        estimated_cost_usd=Decimal("0.25"),
    )
    session.add(row)
    session.commit()
    try:
        assert service.spent_today_usd() == pytest.approx(before + 0.25)
    finally:
        session.delete(row)
        session.commit()
