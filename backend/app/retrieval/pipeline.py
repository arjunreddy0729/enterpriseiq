"""The hybrid retrieval pipeline.

    query
      |
      +--> keyword search (top 50) --+
      |                              +--> RRF fusion --> top 30 --> [reranker, V2]
      +--> vector search  (top 50) --+

Both retrievers run against the same access predicate, so the fused set can
only contain chunks the caller was already entitled to read. The fused set is
then re-checked in application code (filters.enforce_access) as a second,
independent control; in normal operation it removes nothing.

The candidate counts are deliberate. Cheap retrievers cast a wide net to buy
*recall*; the expensive cross-encoder, when enabled, narrows it to buy
*precision*. Retrieving only 20 and reranking to 6 would cap the reranker's
ceiling at whatever the cheap retrievers already ranked in the top 20 - it can
reorder that set but it cannot rescue anything from position 34.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.retrieval.filters import enforce_access
from app.retrieval.fusion import reciprocal_rank_fusion
from app.retrieval.keyword import KeywordRetriever
from app.retrieval.ports import Embedder, Reranker
from app.retrieval.types import Candidate, Filters, RetrievalQuery
from app.retrieval.vector import VectorRetriever

logger = get_logger(__name__)


@dataclass(slots=True)
class RetrievalResult:
    """Fused candidates plus everything needed to explain how they got there."""

    candidates: list[Candidate]
    keyword_count: int
    vector_count: int
    fused_count: int
    timings_ms: dict[str, int] = field(default_factory=dict)
    reranked: bool = False

    def to_debug(self) -> dict[str, Any]:
        return {
            "keyword_candidates": self.keyword_count,
            "vector_candidates": self.vector_count,
            "fused_candidates": self.fused_count,
            "reranked": self.reranked,
            "timings_ms": self.timings_ms,
        }


class HybridRetrievalPipeline:
    """Runs both retrievers, fuses, and optionally reranks."""

    def __init__(
        self,
        session: Session,
        embedder: Embedder,
        reranker: Reranker | None = None,
    ) -> None:
        self._session = session
        self._keyword = KeywordRetriever(session)
        self._vector = VectorRetriever(session, embedder)
        self._reranker = reranker
        self._settings = get_settings()

    def retrieve(
        self,
        text: str,
        allowed_group_ids: tuple[int, ...],
        filters: Filters | None = None,
        top_k: int | None = None,
    ) -> RetrievalResult:
        settings = self._settings
        filters = filters or Filters()
        timings: dict[str, int] = {}

        keyword_query = RetrievalQuery(
            text=text,
            allowed_group_ids=allowed_group_ids,
            filters=filters,
            limit=settings.retrieval_keyword_top_k,
        )
        vector_query = RetrievalQuery(
            text=text,
            allowed_group_ids=allowed_group_ids,
            filters=filters,
            limit=settings.retrieval_vector_top_k,
        )

        started = time.perf_counter()
        keyword_hits = self._keyword.search(keyword_query)
        timings["keyword_ms"] = _elapsed(started)

        started = time.perf_counter()
        vector_hits = self._vector.search(vector_query)
        timings["vector_ms"] = _elapsed(started)

        started = time.perf_counter()
        fused = reciprocal_rank_fusion(
            keyword_hits,
            vector_hits,
            k=settings.rrf_k,
            limit=settings.retrieval_fusion_top_k,
        )
        timings["fusion_ms"] = _elapsed(started)

        # Defense in depth: re-verify every ACL before anything leaves this
        # function. Both retrievers already filtered in SQL.
        fused = enforce_access(fused, allowed_group_ids)

        result = RetrievalResult(
            candidates=fused,
            keyword_count=len(keyword_hits),
            vector_count=len(vector_hits),
            fused_count=len(fused),
            timings_ms=timings,
        )

        limit = top_k or settings.retrieval_rerank_top_k
        if self._reranker is not None and fused:
            started = time.perf_counter()
            result.candidates = self._reranker.rerank(text, fused, limit)
            timings["rerank_ms"] = _elapsed(started)
            result.reranked = True
        else:
            result.candidates = fused[:limit]

        logger.info(
            "retrieval_complete",
            query_length=len(text),
            keyword=result.keyword_count,
            vector=result.vector_count,
            fused=result.fused_count,
            returned=len(result.candidates),
            reranked=result.reranked,
            **timings,
        )
        return result


def _elapsed(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
