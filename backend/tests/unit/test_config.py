"""Configuration behaviour that other layers depend on."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from app.core.config import (
    MODEL_PRICING_USD_PER_MTOK,
    Settings,
    estimate_cost_usd,
)


@pytest.fixture(autouse=True)
def _no_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """DATABASE_URL replaces the POSTGRES_* parts these tests build URLs from,
    so a value in the environment (as in a run against the embedded demo
    database) must not leak in."""
    monkeypatch.delenv("DATABASE_URL", raising=False)


def make_settings(**overrides: object) -> Settings:
    """Build Settings ignoring any .env on the machine running the tests."""
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


class TestDatabaseUrl:
    def test_uses_psycopg3_driver(self) -> None:
        settings = make_settings()
        assert settings.database_url.startswith("postgresql+psycopg://")

    def test_includes_host_port_and_database(self) -> None:
        settings = make_settings(postgres_host="db", postgres_port=5432, postgres_db="enterpriseiq")
        assert "@db:5432/enterpriseiq" in settings.database_url

    def test_password_with_special_characters_is_url_encoded(self) -> None:
        settings = make_settings(postgres_password=SecretStr("p@ss:w/rd"))
        # Raw '@' or '/' in the password would corrupt the URL.
        assert "p%40ss%3Aw%2Frd" in settings.database_url

    def test_safe_url_masks_the_password(self) -> None:
        settings = make_settings(postgres_password=SecretStr("hunter2"))
        assert "hunter2" not in settings.safe_database_url
        assert ":***@" in settings.safe_database_url


class TestEmbeddingPrefix:
    def test_prefix_always_ends_with_exactly_one_space(self) -> None:
        # BGE is asymmetric: the query prefix must be present and correctly
        # spaced or retrieval quality drops measurably.
        assert make_settings(
            embedding_query_prefix="Represent this sentence:"
        ).embedding_query_prefix.endswith(": ")
        assert make_settings(
            embedding_query_prefix="Represent this sentence:    "
        ).embedding_query_prefix.endswith(": ")

    def test_empty_prefix_stays_empty(self) -> None:
        assert make_settings(embedding_query_prefix="").embedding_query_prefix == ""


class TestLlmConfigured:
    def test_missing_key_is_not_configured(self) -> None:
        assert make_settings(anthropic_api_key=None).llm_configured is False

    def test_placeholder_key_is_not_configured(self) -> None:
        settings = make_settings(anthropic_api_key=SecretStr("sk-ant-REPLACE_ME"))
        assert settings.llm_configured is False

    def test_real_looking_key_is_configured(self) -> None:
        settings = make_settings(anthropic_api_key=SecretStr("sk-ant-api03-abc123"))
        assert settings.llm_configured is True

    def test_default_model_is_a_known_priced_model(self) -> None:
        # If the default model is not in the pricing table, cost tracking
        # silently reports $0 for every request.
        assert make_settings().anthropic_model in MODEL_PRICING_USD_PER_MTOK


class TestCostEstimation:
    def test_known_model_uses_published_rates(self) -> None:
        # claude-opus-5: $5.00 / MTok in, $25.00 / MTok out.
        cost = estimate_cost_usd("claude-opus-5", input_tokens=1_000_000, output_tokens=0)
        assert cost == pytest.approx(5.00)

        cost = estimate_cost_usd("claude-opus-5", input_tokens=0, output_tokens=1_000_000)
        assert cost == pytest.approx(25.00)

    def test_realistic_rag_request(self) -> None:
        # ~4k tokens of context in, ~300 tokens of answer out.
        cost = estimate_cost_usd("claude-opus-5", input_tokens=4_000, output_tokens=300)
        assert cost == pytest.approx(4_000 * 5 / 1e6 + 300 * 25 / 1e6)
        assert 0 < cost < 0.05

    def test_unknown_model_returns_zero_rather_than_raising(self) -> None:
        # A missing price entry must never break a user's query.
        assert estimate_cost_usd("some-future-model", 1000, 1000) == 0.0

    def test_every_priced_model_has_output_dearer_than_input(self) -> None:
        for model, (inp, out) in MODEL_PRICING_USD_PER_MTOK.items():
            assert out > inp > 0, model


class TestCorsOrigins:
    def test_splits_and_strips(self) -> None:
        settings = make_settings(cors_allow_origins="http://a.test, http://b.test ,")
        assert settings.cors_origins == ["http://a.test", "http://b.test"]


def test_pasted_whitespace_is_stripped_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """A trailing space in POSTGRES_SSLMODE took the first public deploy down."""
    from app.core.config import Settings

    monkeypatch.setenv("POSTGRES_SSLMODE", "require ")
    monkeypatch.setenv("POSTGRES_HOST", " db.example.com\n")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-abc123 \n")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.postgres_host == "db.example.com"
    assert settings.database_url.endswith("?sslmode=require")
    assert settings.anthropic_api_key is not None
    assert settings.anthropic_api_key.get_secret_value() == "sk-ant-api03-abc123"
    assert settings.embedding_query_prefix.endswith(": "), "BGE prefix keeps its one space"


def test_database_url_override_wins_and_uses_psycopg(monkeypatch: pytest.MonkeyPatch) -> None:
    """The demo's embedded Postgres is reached over a Unix socket, which only
    a full URL can express."""
    from app.core.config import Settings

    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:@/postgres?host=/tmp/pg")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.database_url == "postgresql+psycopg://postgres:@/postgres?host=/tmp/pg"
    assert "tmp/pg" not in settings.safe_database_url


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("0.8.0", True),
        ("0.10.1", True),
        ("1.0", True),
        ("0.7.4", False),
        ("0.6.2", False),
        (None, False),
        ("", False),
        ("dev", False),
    ],
)
def test_pgvector_version_gate(version: str | None, expected: bool) -> None:
    from app.retrieval.vector import pgvector_at_least

    assert pgvector_at_least(version, (0, 8)) is expected
