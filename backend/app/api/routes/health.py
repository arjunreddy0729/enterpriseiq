"""Liveness and readiness endpoints.

The split matters and is worth being able to defend:

  /healthz  liveness  - "is this process alive?" Touches no dependency. If it
                        fails, the orchestrator should restart the container.
  /readyz   readiness - "can this process serve a real request?" Checks the
                        database, the pgvector extension, the migration
                        version, the embedding dimension, and the seed data.
                        If it fails, the orchestrator should stop sending
                        traffic here - but restarting would not help.

Wiring a database call into the liveness probe is a classic way to turn a brief
database blip into a cluster-wide restart storm.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import BACKEND_ROOT, Settings, get_settings
from app.db.session import get_session
from app.schemas.health import ComponentCheck, LivenessResponse, ReadinessResponse

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=LivenessResponse, summary="Liveness probe")
def healthz(settings: Settings = Depends(get_settings)) -> LivenessResponse:
    return LivenessResponse(
        app=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
    )


def _alembic_head_revision() -> str | None:
    """The newest revision on disk, or None if Alembic is not importable here."""
    try:
        from alembic.config import Config as AlembicConfig
        from alembic.script import ScriptDirectory

        cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
        return ScriptDirectory.from_config(cfg).get_current_head()
    except Exception:  # pragma: no cover - environment-dependent
        return None


def _check_database(session: Session) -> ComponentCheck:
    try:
        session.execute(text("SELECT 1"))
        return ComponentCheck(name="database", status="ok")
    except Exception as exc:
        return ComponentCheck(name="database", status="fail", detail=str(exc))


def _check_pgvector(session: Session) -> ComponentCheck:
    try:
        version = session.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        ).scalar_one_or_none()
    except Exception as exc:
        return ComponentCheck(name="pgvector", status="fail", detail=str(exc))
    if version is None:
        return ComponentCheck(
            name="pgvector",
            status="fail",
            detail="extension 'vector' is not installed; run `alembic upgrade head`",
        )
    return ComponentCheck(name="pgvector", status="ok", detail=f"v{version}")


def _check_migrations(session: Session) -> ComponentCheck:
    try:
        applied = session.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one_or_none()
    except Exception as exc:
        return ComponentCheck(
            name="migrations",
            status="fail",
            detail=f"alembic_version unreadable ({exc}); run `alembic upgrade head`",
        )
    if applied is None:
        return ComponentCheck(name="migrations", status="fail", detail="no migration applied")
    head = _alembic_head_revision()
    if head is None:
        return ComponentCheck(
            name="migrations", status="ok", detail=f"applied={applied} (head unknown)"
        )
    if applied != head:
        return ComponentCheck(
            name="migrations",
            status="fail",
            detail=f"applied={applied} but head={head}; run `alembic upgrade head`",
        )
    return ComponentCheck(name="migrations", status="ok", detail=f"at head {head}")


def _check_embedding_dim(session: Session, settings: Settings) -> ComponentCheck:
    """Guard against a silent embedding-model / column-dimension mismatch.

    pgvector stores the declared dimension in pg_attribute.atttypmod. If
    EMBEDDING_DIM was changed after the schema was created, every insert would
    fail at write time and every search would be meaningless - better to fail
    the readiness probe with an explicit message.
    """
    try:
        typmod = session.execute(
            text(
                "SELECT atttypmod FROM pg_attribute "
                "WHERE attrelid = 'public.chunks'::regclass "
                "AND attname = 'embedding' AND NOT attisdropped"
            )
        ).scalar_one_or_none()
    except Exception as exc:
        return ComponentCheck(name="embedding_dim", status="fail", detail=str(exc))

    if typmod is None:
        return ComponentCheck(
            name="embedding_dim", status="fail", detail="chunks.embedding column not found"
        )
    if typmod != settings.embedding_dim:
        return ComponentCheck(
            name="embedding_dim",
            status="fail",
            detail=(
                f"chunks.embedding is vector({typmod}) but EMBEDDING_DIM={settings.embedding_dim}. "
                "Changing the embedding model requires a re-index migration."
            ),
        )
    return ComponentCheck(
        name="embedding_dim",
        status="ok",
        detail=f"vector({typmod}) matches {settings.embedding_model}",
    )


def _check_seed(session: Session) -> ComponentCheck:
    try:
        groups: int = session.execute(text("SELECT count(*) FROM groups")).scalar_one()
        users: int = session.execute(text("SELECT count(*) FROM users")).scalar_one()
    except Exception as exc:
        return ComponentCheck(name="seed", status="fail", detail=str(exc))
    if groups == 0 or users == 0:
        return ComponentCheck(
            name="seed",
            status="degraded",
            detail=(f"{groups} groups / {users} users; run `python -m scripts.seed_users`"),
        )
    return ComponentCheck(name="seed", status="ok", detail=f"{groups} groups, {users} users")


def _check_llm(settings: Settings) -> ComponentCheck:
    """Not required for retrieval; /search works without a key on purpose."""
    if settings.llm_configured:
        return ComponentCheck(name="llm", status="ok", detail=settings.anthropic_model)
    return ComponentCheck(
        name="llm",
        status="degraded",
        detail="ANTHROPIC_API_KEY not set; retrieval works, generation will 503",
    )


@router.get(
    "/readyz",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
)
def readyz(
    response: Response,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ReadinessResponse:
    checks: list[ComponentCheck] = [_check_database(session)]

    # Only probe deeper if the connection itself works; otherwise every
    # subsequent check reports the same connection error.
    if checks[0].status == "ok":
        checks.extend(
            [
                _check_pgvector(session),
                _check_migrations(session),
                _check_embedding_dim(session, settings),
                _check_seed(session),
            ]
        )
    checks.append(_check_llm(settings))

    failed = any(c.status == "fail" for c in checks)
    if failed:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(
        status="not_ready" if failed else "ready",
        app=settings.app_name,
        version=settings.app_version,
        checks=checks,
    )


@router.get("/", include_in_schema=False)
def root(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "docs": "/docs",
        "health": {"liveness": "/healthz", "readiness": "/readyz"},
    }
