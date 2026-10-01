"""Core retrieval types.

The important thing in this module is `RetrievalQuery`. It carries the
caller's access groups as a **required** field, so it is impossible to build a
retrieval request that has not decided who is asking. Every retriever takes
this object and nothing else, which means there is no code path anywhere in
the system that fetches chunks without an access predicate.

That is deliberate. The usual way permission-aware retrieval goes wrong is not
a missing check - it is a check that runs one step too late: fetch the top 20,
then drop the ones the user cannot see. Two things break. The obvious one is
that restricted text has already left the database. The subtle one is that you
asked for 20 and got 3, and your recall silently collapsed without any error.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from enum import StrEnum


class RetrieverKind(StrEnum):
    KEYWORD = "keyword"
    VECTOR = "vector"
    FUSED = "fused"


@dataclass(frozen=True, slots=True)
class Filters:
    """Metadata narrowing, applied in SQL alongside the access predicate."""

    departments: tuple[str, ...] = ()
    doc_types: tuple[str, ...] = ()
    classifications: tuple[str, ...] = ()
    updated_after: dt.date | None = None
    updated_before: dt.date | None = None

    @property
    def is_empty(self) -> bool:
        return not any(
            (
                self.departments,
                self.doc_types,
                self.classifications,
                self.updated_after,
                self.updated_before,
            )
        )


@dataclass(frozen=True, slots=True)
class RetrievalQuery:
    """One retrieval request.

    `allowed_group_ids` has no default. Forgetting it is a TypeError at the
    call site rather than a silent security hole at runtime. An empty tuple is
    legal and means "this user can see nothing", which correctly returns zero
    results rather than everything.
    """

    text: str
    allowed_group_ids: tuple[int, ...]
    filters: Filters = field(default_factory=Filters)
    limit: int = 50

    def __post_init__(self) -> None:
        if not isinstance(self.allowed_group_ids, tuple):
            raise TypeError(
                "allowed_group_ids must be a tuple - a list is mutable and this "
                "value decides what the caller is allowed to read"
            )
        if self.limit < 1:
            raise ValueError("limit must be >= 1")

    @property
    def sees_nothing(self) -> bool:
        """True when the caller belongs to no groups at all."""
        return not self.allowed_group_ids


@dataclass(slots=True)
class Candidate:
    """One chunk returned by a retriever, with its provenance.

    Ranks from each retriever are kept separately rather than collapsed into a
    single score. Fusion needs the ranks, and when an answer is wrong the first
    question is always "which retriever found this, and where did it place it?"
    """

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    content: str
    embed_text: str
    section_path: str | None
    document_title: str
    source_uri: str
    department: str | None
    doc_type: str | None
    classification: str | None
    chunk_index: int
    page_from: int | None = None
    page_to: int | None = None
    source_updated_at: dt.datetime | None = None
    #: The chunk's ACL as stored, carried out of the database so the
    #: application can re-check it (see filters.enforce_access).
    access_group_ids: tuple[int, ...] = ()

    #: Raw score from whichever retriever produced this row.
    keyword_score: float | None = None
    vector_score: float | None = None
    #: 1-indexed position within each retriever's own result list.
    keyword_rank: int | None = None
    vector_rank: int | None = None
    #: Reciprocal-rank-fusion score, filled in by the fuser.
    rrf_score: float | None = None
    #: Cross-encoder score, filled in by the reranker (V2).
    rerank_score: float | None = None

    @property
    def retrieved_by(self) -> tuple[str, ...]:
        found = []
        if self.keyword_rank is not None:
            found.append("keyword")
        if self.vector_rank is not None:
            found.append("vector")
        return tuple(found)

    @property
    def final_score(self) -> float:
        """The score the caller should rank on, best available."""
        if self.rerank_score is not None:
            return self.rerank_score
        if self.rrf_score is not None:
            return self.rrf_score
        return self.vector_score or self.keyword_score or 0.0

    def to_log_entry(self) -> dict[str, object]:
        """Compact form written to query_logs.candidates."""
        return {
            "chunk_id": str(self.chunk_id),
            "keyword_rank": self.keyword_rank,
            "vector_rank": self.vector_rank,
            "keyword_score": self.keyword_score,
            "vector_score": self.vector_score,
            "rrf_score": self.rrf_score,
            "rerank_score": self.rerank_score,
        }
