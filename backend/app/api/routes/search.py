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

from fastapi import APIRouter

from app.api.dependencies import EmbedderDep, IdentityDep, SessionDep
from app.core.logging import get_logger, request_id_var
from app.schemas.search import (
    IdentitySummary,
    SearchDebug,
    SearchRequest,
    SearchResponse,
    SearchResult,
)
from app.services.search_service import SearchService

logger = get_logger(__name__)

router = APIRouter(tags=["search"])


@router.post(
    "/search",
    response_model=SearchResponse,
    summary="Hybrid retrieval, permission-filtered, no LLM",
)
def search(
    payload: SearchRequest,
    session: SessionDep,
    identity: IdentityDep,
    embedder: EmbedderDep,
) -> SearchResponse:
    # From the contextvar the middleware set, NOT from the inbound header.
    # Reading the request header only works when the *client* supplied an id;
    # for everyone else it returned "" and the response - and the query_logs
    # row, and the log lines - had nothing to correlate on. The request id is
    # the thread that ties a bad answer back to the evidence that produced it,
    # so it must always be present.
    request_id = request_id_var.get() or ""

    filters = payload.filters.to_domain() if payload.filters is not None else None
    service = SearchService(session, embedder)

    outcome = service.search(
        query=payload.query,
        identity=identity,
        filters=filters,
        top_k=payload.top_k,
        include_debug=payload.include_debug,
    )
    service.log(request_id, identity, payload.query, filters or _empty_filters(), outcome)

    return SearchResponse(
        request_id=request_id,
        query=payload.query,
        identity=IdentitySummary(
            email=identity.email, name=identity.name, groups=list(identity.group_names)
        ),
        result_count=outcome.result_count,
        results=[SearchResult.from_candidate(c) for c in outcome.candidates],
        took_ms=outcome.took_ms,
        debug=SearchDebug(**outcome.debug) if outcome.debug else None,
    )


def _empty_filters():  # type: ignore[no-untyped-def]
    from app.retrieval.types import Filters

    return Filters()
