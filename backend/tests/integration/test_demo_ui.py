"""The demo web page's logic: same protections as the HTTP API.

The Gradio layout in deploy/huggingface/app.py only wires buttons to these
functions, so this is where the page's behaviour is tested. A stub model keeps
it free.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.core.config import get_settings
from app.core.rate_limit import limiter
from app.generation.llm import StubLLMClient
from app.web import demo_ui
from tests.integration.conftest import requires_corpus

pytestmark = [pytest.mark.integration, requires_corpus]

MARCUS = "Marcus · HR"
PRIYA = "Priya · Engineering"
BONUS = "What are the bonus targets by level?"


@pytest.fixture(autouse=True)
def fresh_limits() -> Iterator[None]:
    limiter.reset()
    yield
    limiter.reset()


def test_every_persona_is_a_seeded_user() -> None:
    from scripts.seed_users import USERS

    seeded = {u.email for u in USERS}
    assert set(demo_ui.PERSONAS.values()) <= seeded


def test_hr_gets_an_answer_with_sources() -> None:
    stub = StubLLMClient("Bonus targets are set by level [1].")
    result = demo_ui.ask(MARCUS, BONUS, "203.0.113.1", llm=stub)

    assert result.answer.startswith("✅ **Answered**")
    assert "hr/compensation-policy.md" in result.sources
    assert "Model called" in result.trace
    assert len(stub.calls) == 1


def test_engineer_is_declined_without_a_model_call() -> None:
    stub = StubLLMClient("should never be used [1].")
    result = demo_ui.ask(PRIYA, BONUS, "203.0.113.2", llm=stub)

    assert result.answer.startswith("🚫 **Declined.**")
    assert "without calling the model" in result.trace
    assert "hr/" not in result.trace, "an HR document must not even be listed as retrieved"
    assert stub.calls == []


def test_search_only_shows_permitted_documents() -> None:
    result = demo_ui.search(PRIYA, BONUS, "203.0.113.3")
    assert "No AI model was called" in result.answer
    assert "hr/compensation-policy.md" not in result.sources
    assert "inside* the database query" in result.trace


@pytest.mark.parametrize(
    ("persona", "question", "message"),
    [
        ("Nobody · Anywhere", BONUS, "Pick who you are asking as."),
        (MARCUS, "  ", "Type a question first."),
        (MARCUS, "x" * 501, "under 500 characters"),
    ],
)
def test_bad_input_is_explained_not_executed(persona: str, question: str, message: str) -> None:
    stub = StubLLMClient()
    result = demo_ui.ask(persona, question, "203.0.113.4", llm=stub)
    assert message in result.answer
    assert stub.calls == []


def test_ai_answers_are_rate_limited_per_visitor(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "rate_limits_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_query_per_hour", 1)

    demo_ui.ask(PRIYA, BONUS, "203.0.113.5", llm=StubLLMClient())
    limited = demo_ui.ask(PRIYA, BONUS, "203.0.113.5", llm=StubLLMClient())
    other_visitor = demo_ui.ask(PRIYA, BONUS, "203.0.113.6", llm=StubLLMClient())

    assert limited.answer.startswith("⏳")
    assert not other_visitor.answer.startswith("⏳")


def test_spent_budget_is_shown_politely(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "llm_daily_budget_usd", 0.0)
    stub = StubLLMClient("Answer [1].")
    result = demo_ui.ask(MARCUS, BONUS, "203.0.113.7", llm=stub)

    assert result.answer.startswith("⚠️")
    assert "daily budget" in result.answer
    assert stub.calls == []


def test_visitor_address_comes_from_the_proxy_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "forwarded_proxy_hops", 1)
    headers = {"x-forwarded-for": "6.6.6.6, 198.51.100.7"}
    assert demo_ui.client_key(headers, "10.0.0.1") == "198.51.100.7"
