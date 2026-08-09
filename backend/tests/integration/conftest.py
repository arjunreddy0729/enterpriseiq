"""Shared setup for tests that need a live database with an ingested corpus.

These are skipped rather than failed when the database is unavailable, so
`pytest` still works on a fresh clone with nothing running. CI brings the
stack up and runs them for real.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

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

#: Apply to any module that needs an ingested corpus.
requires_corpus = pytest.mark.skipif(not _available, reason=_reason)
