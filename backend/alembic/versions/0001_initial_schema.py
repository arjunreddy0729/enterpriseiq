"""initial schema

Creates the full EnterpriseIQ schema: identity + access control, documents and
chunks (with pgvector and full-text search), BM25 corpus statistics, and the
query log.

Revision ID: 0001
Revises:
Create Date: 2026-08-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op
from app.core.config import get_settings
from app.db.models import TSV_EXPRESSION

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The vector column dimension is configuration-driven so that switching to
# bge-small-en-v1.5 (384d) is a one-line .env change on a fresh database.
# On an EXISTING database, changing it requires a re-index migration - see
# docs/architecture.md. /readyz compares this stored dimension against the
# configured one and fails loudly if they diverge.
EMBEDDING_DIM = get_settings().embedding_dim


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Extensions
    # ------------------------------------------------------------------
    # pgvector must exist before any vector column is declared.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # pg_trgm is not used yet; it lands with fuzzy title matching in V2.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # ------------------------------------------------------------------
    # Identity & access control
    # ------------------------------------------------------------------
    op.create_table(
        "groups",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_groups"),
        sa.UniqueConstraint("name", name="uq_groups_name"),
    )

    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=32), server_default="employee", nullable=False),
        sa.Column("department", sa.String(length=64), nullable=True),
        sa.Column("title", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.CheckConstraint("role IN ('employee', 'admin')", name="ck_users_role"),
    )

    op.create_table(
        "user_groups",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_user_groups_user", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["group_id"], ["groups.id"], name="fk_user_groups_group", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", "group_id", name="pk_user_groups"),
    )

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------
    op.create_table(
        "documents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_uri", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("department", sa.String(length=64), nullable=True),
        sa.Column("doc_type", sa.String(length=64), nullable=True),
        sa.Column("owner", sa.String(length=255), nullable=True),
        sa.Column(
            "classification", sa.String(length=32), server_default="internal", nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_documents"),
        sa.CheckConstraint(
            "status IN ('active', 'superseded', 'deleted')", name="ck_documents_status"
        ),
        sa.CheckConstraint(
            "classification IN ('public', 'internal', 'confidential', 'restricted')",
            name="ck_documents_classification",
        ),
    )
    op.create_index("ix_documents_content_hash", "documents", ["content_hash"])
    op.create_index("ix_documents_department", "documents", ["department", "doc_type"])
    # One live document per source URI; soft-deleted rows do not block re-ingest.
    op.create_index(
        "ux_documents_source_uri",
        "documents",
        ["source_uri"],
        unique=True,
        postgresql_where=sa.text("status <> 'deleted'"),
    )

    op.create_table(
        "document_permissions",
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_document_permissions_document",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["groups.id"],
            name="fk_document_permissions_group",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("document_id", "group_id", name="pk_document_permissions"),
    )

    # ------------------------------------------------------------------
    # Chunks - the retrieval unit
    # ------------------------------------------------------------------
    op.create_table(
        "chunks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("section_path", sa.Text(), nullable=True),
        sa.Column("page_from", sa.Integer(), nullable=True),
        sa.Column("page_to", sa.Integer(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("embedding_model", sa.String(length=128), nullable=False),
        # STORED generated column: Postgres maintains it, the application never
        # writes it, so it cannot drift from `content`.
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed(TSV_EXPRESSION, persisted=True),
            nullable=False,
        ),
        sa.Column(
            "access_group_ids",
            postgresql.ARRAY(sa.Integer()),
            server_default=sa.text("'{}'::integer[]"),
            nullable=False,
        ),
        sa.Column("department", sa.String(length=64), nullable=True),
        sa.Column("doc_type", sa.String(length=64), nullable=True),
        sa.Column("classification", sa.String(length=32), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name="fk_chunks_document", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chunks"),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_chunks_document_index"),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    op.create_index("ix_chunks_department", "chunks", ["department", "doc_type"])
    # GIN on the tsvector: keyword candidate generation.
    op.create_index("ix_chunks_tsv", "chunks", ["tsv"], postgresql_using="gin")
    # GIN on the ACL array: makes `access_group_ids && :user_groups` an index
    # scan. This is THE predicate that enforces permission-aware retrieval.
    op.create_index(
        "ix_chunks_access_group_ids", "chunks", ["access_group_ids"], postgresql_using="gin"
    )
    # HNSW over cosine distance. Chosen over IVFFlat because it needs no
    # training step (works from an empty table) and gives better recall at the
    # same latency. m=16 / ef_construction=64 are pgvector's defaults and a
    # sane starting point for a corpus of this size.
    op.execute(
        "CREATE INDEX ix_chunks_embedding_hnsw ON chunks "
        "USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )
    op.execute(
        f"COMMENT ON COLUMN chunks.embedding IS "
        f"'{EMBEDDING_DIM}-dimensional; must match Settings.embedding_dim'"
    )

    # ------------------------------------------------------------------
    # BM25 corpus statistics
    # ------------------------------------------------------------------
    op.create_table(
        "term_stats",
        sa.Column("term", sa.Text(), nullable=False),
        sa.Column("document_frequency", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("term", name="pk_term_stats"),
    )

    op.create_table(
        "corpus_stats",
        sa.Column("id", sa.Integer(), server_default="1", nullable=False),
        sa.Column("chunk_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "avg_chunk_length",
            sa.Numeric(precision=10, scale=4),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_corpus_stats"),
        sa.CheckConstraint("id = 1", name="ck_corpus_stats_singleton"),
    )
    op.execute("INSERT INTO corpus_stats (id, chunk_count, avg_chunk_length) VALUES (1, 0, 0)")

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------
    op.create_table(
        "query_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("endpoint", sa.String(length=64), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("rewritten_query", sa.Text(), nullable=True),
        sa.Column("filters", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("candidates", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("used_chunk_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=True),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("citations", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("grounding", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("confidence", sa.String(length=16), nullable=True),
        sa.Column("llm_model", sa.String(length=64), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("estimated_cost_usd", sa.Numeric(precision=10, scale=6), nullable=True),
        sa.Column("latency_ms", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_query_logs_user", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_query_logs"),
        sa.CheckConstraint(
            "status IN ('answered', 'insufficient_evidence', 'error', 'retrieval_only')",
            name="ck_query_logs_status",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR confidence IN ('high', 'medium', 'low')",
            name="ck_query_logs_confidence",
        ),
    )
    op.create_index("ix_query_logs_created_at", "query_logs", ["created_at"])
    op.create_index("ix_query_logs_request_id", "query_logs", ["request_id"])
    op.create_index("ix_query_logs_user_id", "query_logs", ["user_id"])


def downgrade() -> None:
    op.drop_table("query_logs")
    op.drop_table("corpus_stats")
    op.drop_table("term_stats")
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw")
    op.drop_table("chunks")
    op.drop_table("document_permissions")
    op.drop_table("documents")
    op.drop_table("user_groups")
    op.drop_table("users")
    op.drop_table("groups")
    # Extensions are intentionally NOT dropped: another database object in the
    # same cluster may depend on them.
