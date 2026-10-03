"""Dense retrieval over pgvector.

Finds chunks whose *meaning* is close to the query, which is what lets
"how do payments log in?" match a passage that says "service-to-service
authentication uses the OAuth 2.0 client credentials grant" without sharing a
single content word.

Two operational details worth knowing:

**Cosine distance.** The index is built with `vector_cosine_ops` and the query
uses `<=>`. Vectors are L2-normalised at embedding time, so distance and
similarity are related by `similarity = 1 - distance` exactly.

**Iterative scans.** An HNSW index walks a graph and stops when it has enough
neighbours - but the ACL predicate is applied to the rows that walk produces.
On a selective filter (an Engineering user against an HR-heavy corpus) the walk
can return 50 neighbours of which 3 survive, so you ask for 50 and get 3, with
no error. pgvector 0.8's `hnsw.iterative_scan` makes the scan keep going until
it has enough *surviving* rows. Without it, permission filtering silently
degrades recall for exactly the users whose access is most restricted.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from sqlalchemy import Select, select, text
from sqlalchemy.orm import Session

from app.db.models import Chunk, Document
from app.retrieval.filters import build_where
from app.retrieval.ports import Embedder
from app.retrieval.types import Candidate, RetrievalQuery, RetrieverKind

#: How hard pgvector works before giving up on finding more surviving rows.
#: Higher = better recall under selective filters, more work per query.
_HNSW_EF_SEARCH = 100
_HNSW_MAX_SCAN_TUPLES = 20_000


def candidate_columns() -> Select:
    """The column set every retriever returns, so Candidate can be built once."""
    return select(
        Chunk.id,
        Chunk.document_id,
        Chunk.content,
        Chunk.section_path,
        Chunk.chunk_index,
        Chunk.department,
        Chunk.doc_type,
        Chunk.classification,
        Chunk.page_from,
        Chunk.page_to,
        Chunk.source_updated_at,
        Chunk.access_group_ids,
        Document.title.label("document_title"),
        Document.source_uri,
    ).join(Document, Document.id == Chunk.document_id)


def row_to_candidate(row: Any) -> Candidate:
    """Build a Candidate from a result row.

    `embed_text` is reconstructed from section_path + content rather than
    stored a second time. It is derivable, and a duplicated copy of every
    chunk's text is a lot of storage to keep consistent for no gain.
    """
    from app.ingestion.chunking import build_embed_text

    heading_path = tuple(p.strip() for p in (row.section_path or "").split(">") if p.strip())
    return Candidate(
        chunk_id=row.id,
        document_id=row.document_id,
        content=row.content,
        embed_text=build_embed_text(row.content, heading_path, include_prefix=True),
        section_path=row.section_path,
        document_title=row.document_title,
        source_uri=row.source_uri,
        department=row.department,
        doc_type=row.doc_type,
        classification=row.classification,
        chunk_index=row.chunk_index,
        page_from=row.page_from,
        page_to=row.page_to,
        source_updated_at=row.source_updated_at,
        access_group_ids=tuple(row.access_group_ids or ()),
    )


class VectorRetriever:
    """Nearest-neighbour search with the access predicate inside the query."""

    def __init__(self, session: Session, embedder: Embedder) -> None:
        self._session = session
        self._embedder = embedder

    @property
    def kind(self) -> str:
        return RetrieverKind.VECTOR

    def search(self, query: RetrievalQuery) -> list[Candidate]:
        if query.sees_nothing or not query.text.strip():
            return []

        vector = self._embedder.embed_query(query.text)
        return self.search_with_vector(query, vector)

    def search_with_vector(self, query: RetrievalQuery, vector: np.ndarray) -> list[Candidate]:
        """Search with a pre-computed query vector.

        Split out so a caller embedding several query variants (query
        rewriting) pays for the model once.
        """
        if query.sees_nothing:
            return []

        self._tune_scan()

        embedding = vector.tolist()
        distance = Chunk.embedding.cosine_distance(embedding)

        statement = (
            candidate_columns()
            .add_columns(distance.label("distance"))
            .where(build_where(query))
            .where(Chunk.embedding.isnot(None))
            .order_by(distance)
            .limit(query.limit)
        )

        candidates: list[Candidate] = []
        for rank, row in enumerate(self._session.execute(statement), start=1):
            candidate = row_to_candidate(row)
            # Vectors are normalised, so this is exact, not an approximation.
            candidate.vector_score = 1.0 - float(row.distance)
            candidate.vector_rank = rank
            candidates.append(candidate)
        return candidates

    def _tune_scan(self) -> None:
        """Session-level pgvector settings.

        Without iterative scans, a restrictive ACL filter silently returns
        fewer rows than requested - the recall of the most restricted users
        degrades first and most, which is the worst possible failure mode for
        a permission-aware system.
        """
        self._session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
        self._session.execute(text(f"SET LOCAL hnsw.ef_search = {_HNSW_EF_SEARCH}"))
        self._session.execute(text(f"SET LOCAL hnsw.max_scan_tuples = {_HNSW_MAX_SCAN_TUPLES}"))
