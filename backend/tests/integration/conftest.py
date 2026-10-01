"""Shared setup for tests that need a live database with an ingested corpus.

These are skipped rather than failed when the database is unavailable, so
`pytest` still works on a fresh clone with nothing running. CI brings the
stack up and runs them for real.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.db.models import Chunk
from app.db.session import SessionLocal


def _corpus_state() -> tuple[bool, str]:
    try:
        with SessionLocal() as session:
            count = session.execute(select(func.count(Chunk.id))).scalar_one()
    except SQLAlchemyError as exc:
        return False, f"database unavailable: {type(exc).__name__}"
    if not count:
        return False, "corpus not ingested - run: python -m scripts.ingest_corpus"
    return True, ""


_available, _reason = _corpus_state()

# Locally, a missing database is a skip so `pytest` is green on a fresh clone.
# In CI it is a failure: a security suite that silently skips proves nothing,
# and that is exactly what happened before CI ingested the corpus.
if not _available and os.environ.get("REQUIRE_INTEGRATION") == "1":
    raise RuntimeError(f"REQUIRE_INTEGRATION=1 but integration tests cannot run: {_reason}")

#: Whether the database is up with an ingested corpus.
CORPUS_AVAILABLE = _available

#: Apply to any module that needs an ingested corpus.
requires_corpus = pytest.mark.skipif(not _available, reason=_reason)


def login(client: TestClient, email: str) -> dict[str, str]:
    """Log in through the real endpoint and return a bearer header."""
    password = get_settings().demo_user_password
    if password is None:
        pytest.skip("DEMO_USER_PASSWORD is not set, so seeded users cannot log in")
    response = client.post(
        "/api/v1/auth/token",
        json={"email": email, "password": password.get_secret_value()},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
