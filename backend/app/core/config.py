"""Application configuration.

Every tunable in EnterpriseIQ lives here and is sourced from the environment
(or .env). Nothing reads os.environ directly anywhere else in the codebase,
and no secret is ever hardcoded.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import quote_plus

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> parents[2] == backend/
BACKEND_ROOT: Path = Path(__file__).resolve().parents[2]
REPO_ROOT: Path = BACKEND_ROOT.parent


# ---------------------------------------------------------------------------
# LLM pricing
# ---------------------------------------------------------------------------
# USD per 1,000,000 tokens, as (input, output). Used for cost estimation in
# query_logs and the evaluation report. These are list prices and can change -
# the numbers we report are always labelled "estimated", never billed truth.
MODEL_PRICING_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-fable-5": (10.00, 50.00),
}


def model_price(model: str) -> tuple[float, float] | None:
    """Price for a model id, tolerating dated snapshots.

    `claude-haiku-4-5-20251001` is priced as `claude-haiku-4-5`. Without this,
    a dated model id would price at $0 and silently disable the spend cap.
    """
    if model in MODEL_PRICING_USD_PER_MTOK:
        return MODEL_PRICING_USD_PER_MTOK[model]
    matches = [key for key in MODEL_PRICING_USD_PER_MTOK if model.startswith(f"{key}-")]
    return MODEL_PRICING_USD_PER_MTOK[max(matches, key=len)] if matches else None


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate the USD cost of one LLM call.

    Returns 0.0 for an unknown model rather than raising: a missing price entry
    must never break a user's query. The caller is expected to log the miss.
    """
    price = model_price(model)
    if price is None:
        return 0.0
    input_price, output_price = price
    return (input_tokens * input_price + output_tokens * output_price) / 1_000_000


class Settings(BaseSettings):
    """Runtime configuration, populated from environment variables / .env."""

    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application -------------------------------------------------------
    app_name: str = "EnterpriseIQ"
    app_version: str = "0.1.0"
    environment: Literal["local", "ci", "production"] = "local"
    log_level: str = "INFO"
    log_format: Literal["console", "json"] = "console"
    api_v1_prefix: str = "/api/v1"
    cors_allow_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # --- Authentication ----------------------------------------------------
    #: HMAC key for signing access tokens. Required to issue or accept a JWT;
    #: generate one with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
    jwt_secret: SecretStr | None = None
    jwt_issuer: str = "enterpriseiq"
    jwt_audience: str = "enterpriseiq-api"
    access_token_ttl_minutes: int = Field(default=60, ge=1, le=24 * 60)
    #: Accept `X-Dev-User: <email>` with no password. Convenient for curl and
    #: the existing tests; refused outright in production (see the validator).
    auth_dev_header_enabled: bool = True
    #: Password given to every seeded demo user. Unset means seeded users have
    #: no password and can only be used through the dev header.
    demo_user_password: SecretStr | None = None

    # --- Public demo -----------------------------------------------------
    #: Turns on everything a public deployment needs: rate limits, a daily
    #: model-spend cap, read-only admin endpoints, hidden visitor queries in
    #: the audit trail, and the landing page at /. See docs/deploy.md.
    demo_mode: bool = False
    #: Hard ceiling on estimated model spend per UTC day, across all visitors.
    #: None means no cap; required when demo_mode is on.
    llm_daily_budget_usd: float | None = Field(default=None, ge=0)
    #: Per-client limits, applied when demo_mode is on (or forced on here).
    rate_limits_enabled: bool = False
    rate_limit_login_per_minute: int = Field(default=10, ge=1)
    rate_limit_search_per_minute: int = Field(default=30, ge=1)
    rate_limit_query_per_hour: int = Field(default=15, ge=1)
    #: How many reverse proxies sit in front of the app. The client address is
    #: taken from that position in X-Forwarded-For, counting from the right,
    #: because entries to the left of it are whatever the client chose to send.
    #: 0 means use the socket address (no proxy).
    forwarded_proxy_hops: int = Field(default=0, ge=0, le=5)
    #: Shown on the landing page.
    demo_repo_url: str = "https://github.com/arjunreddy0729/enterpriseiq"
    #: Where a web UI is mounted, if the deployment has one (the Hugging Face
    #: Space mounts a Gradio UI). When set, / redirects there instead of
    #: serving the static landing page.
    demo_ui_path: str | None = None

    # --- PostgreSQL --------------------------------------------------------
    postgres_host: str = "localhost"
    postgres_port: int = 5433
    postgres_user: str = "enterpriseiq"
    postgres_password: SecretStr = SecretStr("enterpriseiq")
    postgres_db: str = "enterpriseiq"
    #: "require" for hosted Postgres such as Neon or Supabase. Unset locally.
    postgres_sslmode: str | None = None
    #: A complete connection URL, used instead of the POSTGRES_* parts when
    #: set. The public demo's embedded Postgres listens on a Unix socket, which
    #: host/port fields cannot express: postgresql://user@/db?host=/tmp/dir
    database_url_override: SecretStr | None = Field(default=None, alias="DATABASE_URL")
    db_echo: bool = False
    db_pool_size: int = 5
    db_max_overflow: int = 10

    # --- Embeddings --------------------------------------------------------
    embedding_model: str = "BAAI/bge-base-en-v1.5"
    embedding_dim: int = 768
    embedding_batch_size: int = 32
    # BGE models are trained with an asymmetric prefix applied to QUERIES ONLY.
    # Documents are embedded with no prefix. Getting this backwards (or
    # skipping it) measurably degrades retrieval.
    embedding_query_prefix: str = "Represent this sentence for searching relevant passages: "

    # --- Reranking (implemented, measured, off by default) -----------------
    reranker_model: str = "BAAI/bge-reranker-base"
    reranker_enabled: bool = False

    # --- Anthropic ---------------------------------------------------------
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-opus-5"
    #: Caps thinking AND answer text together on Claude 4.6+ models, so this
    #: needs headroom above the length of the answer we actually want.
    anthropic_max_tokens: int = 2048
    #: low is right for grounded extraction: the reasoning is "read these
    #: passages and report what they say", not open-ended problem solving.
    anthropic_effort: Literal["low", "medium", "high"] = "low"
    anthropic_timeout_seconds: float = 60.0
    anthropic_max_retries: int = 2

    # --- Generation --------------------------------------------------------
    #: If no retrieved passage reaches this cosine similarity to the question,
    #: abstain WITHOUT calling the model. Retrieval returning nothing relevant
    #: is the most common cause of a hallucinated answer, and the cheapest to
    #: catch.
    #:
    #: Deliberately NOT the fused RRF score. RRF is built from ranks, so the
    #: best candidate scores ~1/61 + 1/61 whether or not it is relevant: on the
    #: benchmark every question, answerable or not, scored 0.0300-0.0328, and
    #: no threshold could separate them. Cosine similarity is absolute. Every
    #: question that must be declined scored <= 0.572 and every answerable one
    #: >= 0.634; 0.60 is the midpoint of that gap. Measured on 35 cases only,
    #: so the model's own abstention stays as the second line of defense.
    generation_min_similarity: float = Field(default=0.60, ge=0.0, le=1.0)
    #: A sentence must reach this support score against its cited chunks to
    #: count as grounded.
    grounding_support_threshold: float = 0.45
    #: Fraction of claim sentences that must be supported for the answer to be
    #: considered grounded overall.
    grounding_pass_threshold: float = 0.7

    # --- Retrieval ---------------------------------------------------------
    # Cheap retrievers cast a wide net (recall); the expensive cross-encoder
    # narrows it (precision). See README "Why these numbers".
    retrieval_keyword_top_k: int = 50
    retrieval_vector_top_k: int = 50
    retrieval_fusion_top_k: int = 30
    retrieval_rerank_top_k: int = 6
    rrf_k: int = 60
    context_token_budget: int = 3000

    # --- Chunking ----------------------------------------------------------
    chunk_target_tokens: int = 450
    chunk_max_tokens: int = 700
    chunk_overlap_tokens: int = 60

    # --- Corpus / seeding --------------------------------------------------
    corpus_dir: Path = Field(default=REPO_ROOT / "corpus")
    seed_on_startup: bool = True

    @model_validator(mode="before")
    @classmethod
    def _strip_surrounding_whitespace(cls, data: object) -> object:
        """Drop spaces and newlines around every value, secrets included.

        Values pasted into a hosting dashboard often carry a stray trailing
        space or newline, and nothing here is valid with one: a host, an API
        key, `sslmode=require ` (which Postgres rejects, and which took the
        first public deploy down). The BGE query prefix needs its trailing
        space, which _normalise_prefix adds back.
        """
        if isinstance(data, dict):
            return {k: v.strip() if isinstance(v, str) else v for k, v in data.items()}
        return data

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        return value.upper()

    @field_validator("embedding_query_prefix")
    @classmethod
    def _normalise_prefix(cls, value: str) -> str:
        # .env files strip nothing, so a trailing space in the value is easy to
        # lose. Guarantee exactly one trailing space if a prefix is set at all.
        value = value.rstrip()
        return f"{value} " if value else ""

    @model_validator(mode="after")
    def _demo_is_safe_to_expose(self) -> Settings:
        """A public demo with no spend cap, or a cap that cannot be measured,
        is an open tab on the Anthropic account. Refuse to start instead."""
        if not self.demo_mode:
            return self
        if self.llm_daily_budget_usd is None:
            raise ValueError("DEMO_MODE requires LLM_DAILY_BUDGET_USD")
        if model_price(self.anthropic_model) is None:
            raise ValueError(
                f"DEMO_MODE requires a known price for ANTHROPIC_MODEL={self.anthropic_model}; "
                "without one the spend cap cannot be enforced"
            )
        if self.demo_user_password is None:
            raise ValueError("DEMO_MODE requires DEMO_USER_PASSWORD so visitors can log in")
        return self

    @property
    def rate_limits_active(self) -> bool:
        return self.demo_mode or self.rate_limits_enabled

    @model_validator(mode="after")
    def _production_auth_is_real(self) -> Settings:
        """Fail at startup, not at the first request, if production would be
        running with password-less or forgeable authentication."""
        if self.environment != "production":
            return self
        if self.auth_dev_header_enabled:
            raise ValueError("AUTH_DEV_HEADER_ENABLED must be false in production")
        secret = self.jwt_secret.get_secret_value() if self.jwt_secret else ""
        if len(secret) < 32:
            raise ValueError("JWT_SECRET must be set to at least 32 characters in production")
        return self

    # --- Derived values ----------------------------------------------------
    @property
    def database_url(self) -> str:
        """SQLAlchemy URL using psycopg 3 (`postgresql+psycopg://`)."""
        if self.database_url_override is not None:
            url = self.database_url_override.get_secret_value()
            for prefix in ("postgresql://", "postgres://"):
                if url.startswith(prefix):
                    return "postgresql+psycopg://" + url[len(prefix) :]
            return url
        password = quote_plus(self.postgres_password.get_secret_value())
        user = quote_plus(self.postgres_user)
        url = (
            f"postgresql+psycopg://{user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )
        return f"{url}?sslmode={self.postgres_sslmode}" if self.postgres_sslmode else url

    @property
    def safe_database_url(self) -> str:
        """Same URL with the password masked - safe to log."""
        if self.database_url_override is not None:
            return "DATABASE_URL (not logged)"
        user = quote_plus(self.postgres_user)
        return (
            f"postgresql+psycopg://{user}:***"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]

    @property
    def llm_configured(self) -> bool:
        """True only when a plausible Anthropic key is present.

        Guards the generation layer so a missing key produces a clear error at
        the API boundary instead of a stack trace from the SDK.
        """
        if self.anthropic_api_key is None:
            return False
        value = self.anthropic_api_key.get_secret_value().strip()
        return bool(value) and not value.endswith("REPLACE_ME")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor. Call `get_settings.cache_clear()` in tests."""
    return Settings()
