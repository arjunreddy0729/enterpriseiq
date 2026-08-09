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

from pydantic import Field, SecretStr, field_validator
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


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate the USD cost of one LLM call.

    Returns 0.0 for an unknown model rather than raising: a missing price entry
    must never break a user's query. The caller is expected to log the miss.
    """
    price = MODEL_PRICING_USD_PER_MTOK.get(model)
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

    # --- PostgreSQL --------------------------------------------------------
    postgres_host: str = "localhost"
    postgres_port: int = 5433
    postgres_user: str = "enterpriseiq"
    postgres_password: SecretStr = SecretStr("enterpriseiq")
    postgres_db: str = "enterpriseiq"
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

    # --- Reranking (V2) ----------------------------------------------------
    reranker_model: str = "BAAI/bge-reranker-base"
    reranker_enabled: bool = False

    # --- Anthropic ---------------------------------------------------------
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-opus-5"
    anthropic_max_tokens: int = 2048

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

    # --- Derived values ----------------------------------------------------
    @property
    def database_url(self) -> str:
        """SQLAlchemy URL using psycopg 3 (`postgresql+psycopg://`)."""
        password = quote_plus(self.postgres_password.get_secret_value())
        user = quote_plus(self.postgres_user)
        return (
            f"postgresql+psycopg://{user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def safe_database_url(self) -> str:
        """Same URL with the password masked - safe to log."""
        user = quote_plus(self.postgres_user)
        return (
            f"postgresql+psycopg://{user}:***"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]

    @property
    def manifest_path(self) -> Path:
        return self.corpus_dir / "manifest.yaml"

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
