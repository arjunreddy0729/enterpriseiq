#!/usr/bin/env bash
#
# Container entrypoint: wait for Postgres, migrate, seed, serve.
#
# Migrations run here rather than in a separate init container because there is
# exactly one API replica in local development. In a real deployment this would
# be a Kubernetes Job or an Argo CD PreSync hook so that N replicas do not race
# to apply the same migration.

set -euo pipefail

echo "[entrypoint] waiting for PostgreSQL at ${POSTGRES_HOST:-localhost}:${POSTGRES_PORT:-5432} ..."
python - <<'PY'
import os
import sys
import time

import psycopg

dsn = (
    f"host={os.environ.get('POSTGRES_HOST', 'localhost')} "
    f"port={os.environ.get('POSTGRES_PORT', '5432')} "
    f"user={os.environ.get('POSTGRES_USER', 'enterpriseiq')} "
    f"password={os.environ.get('POSTGRES_PASSWORD', 'enterpriseiq')} "
    f"dbname={os.environ.get('POSTGRES_DB', 'enterpriseiq')}"
)
if os.environ.get("POSTGRES_SSLMODE"):
    dsn += f" sslmode={os.environ['POSTGRES_SSLMODE']}"

deadline = time.monotonic() + 60
attempt = 0
while True:
    attempt += 1
    try:
        with psycopg.connect(dsn, connect_timeout=3):
            print(f"[entrypoint] PostgreSQL is accepting connections (attempt {attempt})")
            break
    except Exception as exc:  # noqa: BLE001 - any failure means "not ready yet"
        if time.monotonic() >= deadline:
            print(f"[entrypoint] giving up after 60s: {exc}", file=sys.stderr)
            sys.exit(1)
        time.sleep(1)
PY

echo "[entrypoint] applying migrations ..."
alembic upgrade head

if [ "${SEED_ON_STARTUP:-true}" = "true" ]; then
  echo "[entrypoint] seeding groups and users ..."
  python -m scripts.seed_users
else
  echo "[entrypoint] SEED_ON_STARTUP=false, skipping seed"
fi

# A hosted deployment has no one to run ingestion by hand, and on a fresh
# database the API would answer every question with "not enough information".
# Ingestion is idempotent (unchanged documents are skipped by content hash),
# so running it on every start costs a few seconds, not a re-embed.
if [ "${INGEST_ON_STARTUP:-false}" = "true" ]; then
  echo "[entrypoint] ingesting the corpus ..."
  python -m scripts.ingest_corpus
fi

RELOAD=""
if [ "${ENVIRONMENT:-local}" = "local" ]; then
  RELOAD="--reload"
fi

echo "[entrypoint] starting uvicorn ..."
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --no-access-log \
  ${RELOAD}
