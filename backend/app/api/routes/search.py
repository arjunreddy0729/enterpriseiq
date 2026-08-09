"""POST /api/v1/search - retrieval with no model in the loop.

This endpoint is the most useful one in the system while it is being built,
which is why it exists before the generation layer does. It answers "what
would the model have been shown?" without spending a token, and that separates
two failure modes that otherwise look identical from the outside:

    bad answer because retrieval found the wrong evidence
    bad answer because the model misread the right evidence

The evaluation harness measures recall against this endpoint, permission tests
assert against it, and every "why did it say that?" investigation starts here.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Request
from sqlalchemy.orm import Session

from app.api.dependencies import EmbedderDep, IdentityDep, SessionDep
from app.core.identity import Identity
from app.core.logging import get_logger
from app.db.models import QueryLog
from app.retrieval.filters import describe
from app.retrieval.keyword import KeywordRetriever
from app.retrieval.pipeline import HybridRetrievalPipeline
from app.retrieval.ports import Embedder
from app.retrieval.types import Filters, RetrievalQuery
from app.schemas.search import (
    IdentitySummary,
    SearchDebug,
    SearchRequest,
    SearchResponse,
    SearchResult,
)

logger = get_logger(__name__)

router = APIRouter(tags=["search"])


@router.post(
    "/search",
    response_model=SearchResponse,
    summary="Hybrid retrieval, permission-filtered, no LLM",
)
def search(
    payload: SearchRequest,
    request: Request,
    session: SessionDep,
    identity: IdentityDep,
    embedder: EmbedderDep,
) -> SearchResponse:
    started = time.perf_counter()
    request_id = request.headers.get("X-Request-ID", "")

    filters: Filters = (
        payload.filters.to_domain() if payload.filters is not None else Filters()
    )

    pipeline = HybridRetrievalPipeline(session, embedder)
    result = pipeline.retrieve(
        text=payload.query,
        # The only source of access groups is the authenticated identity.
        # Nothing in SearchRequest can influence this.
        allowed_group_ids=identity.group_ids,
        filters=filters,
        top_k=payload.top_k,
    )

    took_ms = int((time.perf_counter() - started) * 1000)
    results = [SearchResult.from_candidate(c) for c in result.candidates]

    debug: SearchDebug | None = None
    if payload.include_debug:
        probe = RetrievalQuery(
            text=payload.query,
            allowed_group_ids=identity.group_ids,
            filters=filters,
        )
        debug = SearchDebug(
            **result.to_debug(),
            filters=describe(probe),
            tsquery=KeywordRetriever(session).explain(probe).get("tsquery"),
        )

    _log_search(session, request_id, identity, payload, result, took_ms)

    return SearchResponse(
        request_id=request_id,
        query=payload.query,
        identity=IdentitySummary(
            email=identity.email, name=identity.name, groups=list(identity.group_names)
        ),
        result_count=len(results),
        results=results,
        took_ms=took_ms,
        debug=debug,
    )


def _log_search(
    session: Session,
    request_id: str,
    identity: Identity,
    payload: SearchRequest,
    result: object,
    took_ms: int,
) -> None:
    """Record the request so a bad result can be reconstructed later.

    Best-effort: a logging failure must never fail the user's search.
    """
    try:
        candidates = getattr(result, "candidates", [])
        session.add(
            QueryLog(
                request_id=request_id or "unknown",
                user_id=identity.user_id,
                endpoint="search",
                query=payload.query,
                filters=describe(
                    RetrievalQuery(
                        text=payload.query,
                        allowed_group_ids=identity.group_ids,
                        filters=(
                            payload.filters.to_domain()
                            if payload.filters is not None
                            else Filters()
                        ),
                    )
                ),
                candidates=[c.to_log_entry() for c in candidates],
                used_chunk_ids=[c.chunk_id for c in candidates],
                latency_ms={**getattr(result, "timings_ms", {}), "total": took_ms},
                status="retrieval_only",
            )
        )
        session.commit()
    except Exception:
        logger.warning("query_log_write_failed", exc_info=True)
        session.rollback()
