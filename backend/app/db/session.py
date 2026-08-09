"""Database engine and session management.

Deliberately synchronous. The expensive work in this system - embedding a
query with BGE, scoring 30 pairs with a cross-encoder - is blocking, CPU-bound
work in C extensions. Wrapping it in async would buy false concurrency and
force run_in_executor plumbing through every layer. FastAPI runs plain `def`
route handlers in a threadpool, which gives us real parallelism for exactly
the same code. See README "Why synchronous SQLAlchemy".
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_settings = get_settings()

# create_engine does not connect; the first checkout does. Importing this
# module therefore never requires a live database (unit tests rely on that).
engine: Engine = create_engine(
    _settings.database_url,
    echo=_settings.db_echo,
    pool_pre_ping=True,  # survive Postgres restarts without a stale-connection error
    pool_size=_settings.db_pool_size,
    max_overflow=_settings.db_max_overflow,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
    class_=Session,
)


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped Session."""
    with SessionLocal() as session:
        yield session
