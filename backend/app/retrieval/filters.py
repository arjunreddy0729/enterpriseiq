"""The access predicate. One function, one source of truth.

Every retriever builds its WHERE clause here. There is no second place in the
codebase that decides what a caller may read, which means reviewing the
authorisation logic of this system is reviewing one file.

The predicate itself is a single array-overlap:

    chunks.access_group_ids && :allowed_group_ids

`&&` is PostgreSQL's "do these arrays share at least one element", and it is
backed by a GIN index (ix_chunks_access_group_ids). So the authorisation check
is not a filter applied to results - it is part of the query plan, evaluated
before rows are returned, in the same index scan as everything else.

Why that matters, concretely. The alternative - fetch top-k, then discard the
unauthorised ones in Python - fails twice:

  1. Restricted text has already left the database and passed through
     application memory, logs and any tracing you have enabled. For a document
     that HR marked restricted, that is the whole problem.
  2. You asked for 20 candidates and kept 3. Recall collapsed and nothing
     raised. The system looks like it is working and quietly answers from
     one-sixth of the evidence.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import ColumnElement, and_, false, or_

from app.db.models import Chunk
from app.retrieval.types import RetrievalQuery


def access_predicate(query: RetrievalQuery) -> ColumnElement[bool]:
    """The authorisation clause. Never optional, never bypassable.

    A caller in no groups gets `false`, which returns zero rows - not an
    error, and emphatically not "everything".
    """
    if query.sees_nothing:
        return false()
    # .overlap() renders the && operator, which uses the GIN index.
    return Chunk.access_group_ids.overlap(list(query.allowed_group_ids))


def metadata_predicates(query: RetrievalQuery) -> list[ColumnElement[bool]]:
    """Optional narrowing by department, type, classification and recency.

    Kept separate from the access predicate so that no future refactor can
    accidentally make authorisation look like just another optional filter.
    """
    filters = query.filters
    clauses: list[ColumnElement[bool]] = []

    if filters.departments:
        clauses.append(Chunk.department.in_(list(filters.departments)))
    if filters.doc_types:
        clauses.append(Chunk.doc_type.in_(list(filters.doc_types)))
    if filters.classifications:
        clauses.append(Chunk.classification.in_(list(filters.classifications)))
    if filters.updated_after is not None:
        clauses.append(Chunk.source_updated_at >= filters.updated_after)
    if filters.updated_before is not None:
        clauses.append(Chunk.source_updated_at <= filters.updated_before)

    return clauses


def build_where(query: RetrievalQuery) -> ColumnElement[bool]:
    """Access predicate AND every metadata predicate.

    This is what every retriever puts in its WHERE clause. There is no variant
    that omits the first term.
    """
    return and_(access_predicate(query), *metadata_predicates(query))


def describe(query: RetrievalQuery) -> dict[str, Any]:
    """Human-readable filter summary, for the debug payload and query_logs."""
    filters = query.filters
    return {
        "allowed_group_ids": list(query.allowed_group_ids),
        "departments": list(filters.departments),
        "doc_types": list(filters.doc_types),
        "classifications": list(filters.classifications),
        "updated_after": filters.updated_after.isoformat() if filters.updated_after else None,
        "updated_before": filters.updated_before.isoformat() if filters.updated_before else None,
    }


__all__ = ["access_predicate", "build_where", "describe", "metadata_predicates", "or_"]
