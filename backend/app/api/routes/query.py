"""POST /api/v1/query - the full pipeline, with an answer at the end."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.dependencies import EmbedderDep, IdentityDep, SessionDep
from app.api.errors import ConfigurationError
from app.core.logging import get_logger, request_id_var
from app.generation.llm import AnthropicClient
from app.schemas.query import CitationOut, GroundingOut, QueryRequest, QueryResponse, UsageOut
from app.schemas.search import IdentitySummary
from app.services.query_service import QueryService

logger = get_logger(__name__)

router = APIRouter(tags=["query"])


@router.post(
    "/query",
    response_model=QueryResponse,
    summary="Ask a question and get a citation-grounded answer",
    responses={
        503: {"description": "ANTHROPIC_API_KEY is not configured"},
    },
)
def query(
    payload: QueryRequest,
    session: SessionDep,
    identity: IdentityDep,
    embedder: EmbedderDep,
) -> QueryResponse:
    request_id = request_id_var.get() or ""

    # Raised as a 503 rather than a 500: a missing key is an operator
    # configuration problem, and the message says exactly which one.
    llm = AnthropicClient()

    filters = payload.filters.to_domain() if payload.filters else None
    service = QueryService(session, embedder, llm)

    outcome = service.answer(
        question=payload.query,
        identity=identity,
        filters=filters,
        top_k=payload.top_k,
        include_debug=payload.include_debug,
    )
    service.log(request_id, identity, payload.query, filters or _empty_filters(), outcome)

    return QueryResponse(
        request_id=request_id,
        status=outcome.status,  # type: ignore[arg-type]
        query=payload.query,
        answer=outcome.answer,
        citations=[CitationOut.from_citation(c) for c in outcome.citations],
        confidence=outcome.confidence,  # type: ignore[arg-type]
        confidence_explanation=outcome.confidence_explanation,
        confidence_signals=outcome.signals,
        grounding=GroundingOut(**outcome.grounding),
        identity=IdentitySummary(
            email=identity.email, name=identity.name, groups=list(identity.group_names)
        ),
        timings_ms=outcome.timings_ms,
        usage=UsageOut(**outcome.usage) if outcome.usage else UsageOut(),
        debug=outcome.debug or None,
    )


def _empty_filters():  # type: ignore[no-untyped-def]
    from app.retrieval.types import Filters

    return Filters()


__all__ = ["ConfigurationError", "router"]
