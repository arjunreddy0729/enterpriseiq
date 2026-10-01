"""SQLAlchemy ORM models.

Design notes worth defending in an interview:

1. `chunks.access_group_ids` is DENORMALISED from `document_permissions`.
   The normalised alternative would join chunks -> documents ->
   document_permissions -> user_groups on every retrieval. That join runs
   AFTER the HNSW index scan, which is precisely when we cannot afford it.
   The denormalised int[] with a GIN index collapses the whole ACL check into
   one indexable predicate:  `chunks.access_group_ids && :user_group_ids`.
   The cost is an eventual-consistency window on ACL changes, closed by a
   propagation job. `document_permissions` remains the source of truth.

2. `chunks.tsv` is a STORED generated column, not something the application
   maintains. Postgres recomputes it on write; it can never drift from
   `content`. The heading path is weighted 'A' and the body 'B' so that a
   keyword match in "Payments Service > Authentication" outranks the same word
   buried in a paragraph.

3. `chunks.embedding_model` is stored per row. When we change embedding models
   we can find, and re-embed, exactly the stale rows instead of guessing.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)

# The PostgreSQL ARRAY, not sqlalchemy.ARRAY. Only the dialect-specific type
# exposes the containment comparators, and `.overlap()` renders the `&&`
# operator that the entire access-control predicate is built on. With the
# generic type the ACL check raises AttributeError on the first search.
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import get_settings
from app.db.base import Base

EMBEDDING_DIM = get_settings().embedding_dim

# The exact expression used for the generated tsvector column. Kept as a module
# constant so the migration and the model provably agree.
TSV_EXPRESSION = (
    "setweight(to_tsvector('english'::regconfig, coalesce(section_path, '')), 'A') || "
    "setweight(to_tsvector('english'::regconfig, content), 'B')"
)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


# ---------------------------------------------------------------------------
# Identity & access control
# ---------------------------------------------------------------------------
class Group(Base):
    """An access group. A user's groups are intersected with a document's."""

    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)

    users: Mapped[list[User]] = relationship(secondary="user_groups", back_populates="groups")


class User(Base):
    """An employee. Authenticates with a password for a short-lived JWT; what
    they may read is decided by their groups, resolved on every request."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, server_default="employee")
    department: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str | None] = mapped_column(String(128))
    #: scrypt hash (see app/core/security.py). NULL means no password login.
    password_hash: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    groups: Mapped[list[Group]] = relationship(secondary="user_groups", back_populates="users")

    __table_args__ = (CheckConstraint("role IN ('employee', 'admin')", name="ck_users_role"),)


class UserGroup(Base):
    __tablename__ = "user_groups"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    group_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("groups.id", ondelete="CASCADE"),
        primary_key=True,
    )


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = _uuid_pk()
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_uri: Mapped[str] = mapped_column(Text, nullable=False)
    # sha256 of the normalised extracted text. Serves two purposes: exact
    # duplicate detection at ingest time, and cheap change detection on re-ingest
    # (unchanged hash -> skip parsing, chunking and embedding entirely).
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    department: Mapped[str | None] = mapped_column(String(64))
    doc_type: Mapped[str | None] = mapped_column(String(64))
    owner: Mapped[str | None] = mapped_column(String(255))
    classification: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="internal"
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")

    effective_date: Mapped[dt.date | None] = mapped_column(Date)
    source_updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    doc_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'superseded', 'deleted')", name="ck_documents_status"
        ),
        CheckConstraint(
            "classification IN ('public', 'internal', 'confidential', 'restricted')",
            name="ck_documents_classification",
        ),
        Index("ix_documents_content_hash", "content_hash"),
        Index("ix_documents_department", "department", "doc_type"),
        # Partial unique index: one live document per source URI, but soft-deleted
        # rows can pile up without blocking a re-ingest of the same path.
        Index(
            "ux_documents_source_uri",
            "source_uri",
            unique=True,
            postgresql_where=text("status <> 'deleted'"),
        ),
    )


class DocumentPermission(Base):
    """Source of truth for document ACLs. `chunks.access_group_ids` is a
    denormalised projection of this table, maintained by the ingestion pipeline
    and the ACL-propagation job."""

    __tablename__ = "document_permissions"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    group_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("groups.id", ondelete="CASCADE"),
        primary_key=True,
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)

    # "Payments Service > Authentication > Service-to-service". Prefixed onto
    # the embedded text and weighted 'A' in the tsvector - the single cheapest
    # retrieval win available.
    section_path: Mapped[str | None] = mapped_column(Text)
    page_from: Mapped[int | None] = mapped_column(Integer)
    page_to: Mapped[int | None] = mapped_column(Integer)

    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)

    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False)

    tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(TSV_EXPRESSION, persisted=True),
        nullable=False,
    )

    # --- Denormalised for single-predicate filtering (see module docstring) --
    access_group_ids: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), nullable=False, server_default=text("'{}'::integer[]")
    )
    department: Mapped[str | None] = mapped_column(String(64))
    doc_type: Mapped[str | None] = mapped_column(String(64))
    classification: Mapped[str | None] = mapped_column(String(32))
    source_updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    document: Mapped[Document] = relationship(back_populates="chunks")

    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_chunks_document_index"),
        Index("ix_chunks_document_id", "document_id"),
        Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),
        Index("ix_chunks_access_group_ids", "access_group_ids", postgresql_using="gin"),
        Index("ix_chunks_department", "department", "doc_type"),
        # The HNSW index itself is created in the migration with explicit
        # operator class and build parameters; declaring it here too would make
        # autogenerate try to recreate it.
    )


# ---------------------------------------------------------------------------
# BM25 corpus statistics
# ---------------------------------------------------------------------------
class TermStat(Base):
    """Document frequency per term, for the BM25 rescoring pass.

    Postgres full-text search gives us fast, ACL-filterable candidate
    generation, but ts_rank_cd is NOT BM25 - it has no term-frequency
    saturation curve and normalises length differently. We regenerate real
    BM25 scores over the FTS candidate set using these statistics.
    """

    __tablename__ = "term_stats"

    term: Mapped[str] = mapped_column(Text, primary_key=True)
    document_frequency: Mapped[int] = mapped_column(Integer, nullable=False)


class CorpusStat(Base):
    """Single-row table holding N and avgdl for the BM25 formula."""

    __tablename__ = "corpus_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, server_default="1")
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    avg_chunk_length: Mapped[float] = mapped_column(
        Numeric(10, 4), nullable=False, server_default="0"
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (CheckConstraint("id = 1", name="ck_corpus_stats_singleton"),)


# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------
class QueryLog(Base):
    """One row per /search or /query request.

    This table is what makes a bad answer debuggable. It records what was
    retrieved, in what order, by which retriever, what survived reranking, what
    actually reached the model, and what the model did with it.
    """

    __tablename__ = "query_logs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    endpoint: Mapped[str] = mapped_column(String(64), nullable=False)

    query: Mapped[str] = mapped_column(Text, nullable=False)
    rewritten_query: Mapped[str | None] = mapped_column(Text)
    filters: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # [{chunk_id, keyword_rank, vector_rank, rrf_score, rerank_score}, ...]
    candidates: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    used_chunk_ids: Mapped[list[uuid.UUID] | None] = mapped_column(ARRAY(UUID(as_uuid=True)))
    #: Every document whose text left the database for this request, whether
    #: or not it was cited. GIN-indexed so "who retrieved document X?" is an
    #: index lookup rather than a scan over JSONB.
    retrieved_document_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, server_default=text("'{}'::uuid[]")
    )

    answer: Mapped[str | None] = mapped_column(Text)
    citations: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    grounding: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    confidence: Mapped[str | None] = mapped_column(String(16))

    llm_model: Mapped[str | None] = mapped_column(String(64))
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))

    # {"retrieve": 41, "rerank": 180, "generate": 2300, "verify": 8, "total": 2530}
    latency_ms: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('answered', 'insufficient_evidence', 'error', 'retrieval_only')",
            name="ck_query_logs_status",
        ),
        CheckConstraint(
            "confidence IS NULL OR confidence IN ('high', 'medium', 'low')",
            name="ck_query_logs_confidence",
        ),
        Index("ix_query_logs_created_at", "created_at"),
        Index("ix_query_logs_request_id", "request_id"),
        Index("ix_query_logs_user_id", "user_id"),
        Index(
            "ix_query_logs_retrieved_document_ids",
            "retrieved_document_ids",
            postgresql_using="gin",
        ),
    )


class PermissionChange(Base):
    """Append-only record of every ACL and group-membership change.

    A database trigger (migration 0002) rejects UPDATE and DELETE on this
    table, so the history cannot be rewritten by the application, including
    by a bug in it. Actor and target are stored as text rather than foreign
    keys for the same reason: deleting a user must not need to edit the record
    of what that user did.
    """

    __tablename__ = "permission_changes"

    id: Mapped[uuid.UUID] = _uuid_pk()
    actor_email: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    target_label: Mapped[str] = mapped_column(Text, nullable=False)
    before: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    after: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "action IN ('document_acl', 'user_groups')", name="ck_permission_changes_action"
        ),
        Index("ix_permission_changes_created_at", "created_at"),
        Index("ix_permission_changes_target", "target_id"),
    )
