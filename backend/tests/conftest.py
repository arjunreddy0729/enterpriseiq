"""Shared pytest fixtures.

Unit tests must run with no database and no network. Anything that needs a
live PostgreSQL is marked `@pytest.mark.integration` and skips cleanly when
the database is not reachable, so `pytest` is always green on a fresh clone.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import REPO_ROOT, Settings, get_settings
from app.ingestion.manifest import CorpusManifest, load_manifest


@pytest.fixture(scope="session")
def settings() -> Settings:
    return get_settings()


@pytest.fixture(scope="session")
def corpus_dir() -> Path:
    """Resolve the corpus directory for whichever environment we are in.

    Inside the container CORPUS_DIR=/corpus; on a developer machine it defaults
    to <repo-root>/corpus.
    """
    configured = get_settings().corpus_dir
    if configured.is_dir():
        return configured
    fallback = REPO_ROOT / "corpus"
    if fallback.is_dir():
        return fallback
    pytest.skip(f"corpus directory not found (tried {configured} and {fallback})")


@pytest.fixture(scope="session")
def manifest(corpus_dir: Path) -> CorpusManifest:
    return load_manifest(corpus_dir / "manifest.yaml")


@pytest.fixture
def client() -> Iterator[TestClient]:
    """TestClient over the real app. Touches no database."""
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db_session() -> Iterator[Session]:
    """A live database session, or a skip if PostgreSQL is not up."""
    from app.db.session import SessionLocal

    session = SessionLocal()
    try:
        session.execute(text("SELECT 1"))
    except Exception as exc:
        session.close()
        pytest.skip(f"PostgreSQL not reachable: {exc}")
    try:
        yield session
    finally:
        session.rollback()
        session.close()
