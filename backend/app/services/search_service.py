"""Retrieval orchestration for POST /api/v1/search.

The route that used to hold this built the retrieval pipeline, assembled the
debug payload and wrote the audit row itself - roughly twice the code of the
/query route for a simpler job, and the one place in the API layer that
reached past the service boundary into `retrieval/` and `db/`.

Everything here is the same work; it is only in a place where it can be called
without an HTTP request. That matters for two concrete reasons beyond tidiness:
the evaluation harness and the demo page both need retrieval without going
through FastAPI, and a service is testable without spinning up a TestClient.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.core.identity import Identity
from app.core.logging import get_logger
from app.db.models import QueryLog
from app.retrieval.filters import describe
from app.retrieval.keyword import KeywordRetriever
from app.retrieval.pipeline import HybridRetrievalPipeline
from app.retrieval.ports import Embedder
from app.retrieval.types import Candidate, Filters, RetrievalQuery

logger = get_logger(__name__)


@dataclass(slots=True)
class SearchOutcome:
    """Everything one search produced, independent of how it was requested."""

    candidates: list[Candidate] = field(default_factory=list)
    #: How many each retriever contributed before fusion. Shown in the demo's
    #: "what happened" trace, so they are part of the result, not debug-only.
    keyword_count: int = 0
    vector_count: int = 0
    took_ms: int = 0
    timings_ms: dict[str, int] = field(default_factory=dict)
    #: Populated only when the caller asked for it; shaped for SearchDebug.
    debug: dict[str, Any] | None = None

    @property
    def result_count(self) -> int:
        return len(self.candidates)


class SearchService:
    """Hybrid retrieval, permission-filtered, with no model in the loop."""

    def __init__(self, session: Session, embedder: Embedder) -> None:
        self._session = session
        self._embedder = embedder

    def search(
        self,
        *,
        query: str,
        identity: Identity,
        filters: Filters | None = None,
        top_k: int = 10,
        include_debug: bool = False,
    ) -> SearchOutcome:
        started = time.perf_counter()
        filters = filters or Filters()

        pipeline = HybridRetrievalPipeline(self._session, self._embedder)
        result = pipeline.retrieve(
            text=query,
            # The only source of access groups is the authenticated identity.
            # No field on the request can influence this.
            allowed_group_ids=identity.group_ids,
            filters=filters,
            top_k=top_k,
        )

        took_ms = int((time.perf_counter() - started) * 1000)

        debug: dict[str, Any] | None = None
        if include_debug:
            probe = self._probe(query, identity, filters)
            debug = {
                **result.to_debug(),
                "filters": describe(probe),
                "tsquery": KeywordRetriever(self._session).explain(probe).get("tsquery"),
            }

        return SearchOutcome(
            candidates=result.candidates,
            keyword_count=result.keyword_count,
            vector_count=result.vector_count,
            took_ms=took_ms,
            timings_ms={**result.timings_ms, "total": took_ms},
            debug=debug,
        )

    def log(
        self,
        request_id: str,
        identity: Identity,
        query: str,
        filters: Filters,
        outcome: SearchOutcome,
    ) -> None:
        """Record the request so a bad result can be reconstructed later.

        Best effort: a failure to write the audit row must never fail the
        user's search, so this swallows and rolls back rather than raising.
        """
        try:
            candidates = outcome.candidates
            self._session.add(
                QueryLog(
                    request_id=request_id or "unknown",
                    user_id=identity.user_id,
                    endpoint="search",
                    query=query,
                    filters=describe(self._probe(query, identity, filters)),
                    candidates=[c.to_log_entry() for c in candidates],
                    used_chunk_ids=[c.chunk_id for c in candidates],
                    retrieved_document_ids=list(dict.fromkeys(c.document_id for c in candidates)),
                    latency_ms=outcome.timings_ms,
                    status="retrieval_only",
                )
            )
            self._session.commit()
        except Exception:
            logger.warning("query_log_write_failed", exc_info=True)
            self._session.rollback()

    @staticmethod
    def _probe(query: str, identity: Identity, filters: Filters) -> RetrievalQuery:
        """A RetrievalQuery built only to describe the filters that were used.

        Constructed through the same type as a real search so the recorded
        filters can never drift from the ones actually applied.
        """
        return RetrievalQuery(
            text=query,
            allowed_group_ids=identity.group_ids,
            filters=filters,
        )
