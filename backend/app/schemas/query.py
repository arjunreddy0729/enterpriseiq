"""Request and response models for /api/v1/query."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.generation.citations import Citation
from app.schemas.search import IdentitySummary, SearchFilters


class QueryRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"query": "What are the bonus targets by level?"}]},
    )

    query: str = Field(min_length=3, max_length=1000)
    filters: SearchFilters | None = None
    top_k: int = Field(default=6, ge=1, le=20)
    include_debug: bool = False


class CitationOut(BaseModel):
    """A source the answer actually used.

    Every field here is looked up server-side from the chunk the model
    referenced by number. None of it is generated text, so a citation cannot
    point at a document that does not exist.
    """

    number: int
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    section_path: str | None
    source_uri: str
    updated_at: str | None
    snippet: str

    @classmethod
    def from_citation(cls, citation: Citation) -> CitationOut:
        return cls(
            number=citation.number,
            chunk_id=citation.chunk_id,
            document_id=citation.document_id,
            document_title=citation.document_title,
            section_path=citation.section_path,
            source_uri=citation.source_uri,
            updated_at=citation.updated_at,
            snippet=citation.snippet,
        )


class GroundingOut(BaseModel):
    score: float
    supported: int
    total_claims: int
    passed: bool
    unsupported: list[str] = Field(default_factory=list)


class UsageOut(BaseModel):
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: float | None = None


class QueryResponse(BaseModel):
    request_id: str
    status: Literal["answered", "insufficient_evidence"]
    query: str
    answer: str
    citations: list[CitationOut]
    #: A band, never a percentage. See app/generation/confidence.py for why.
    confidence: Literal["high", "medium", "low"]
    confidence_explanation: str
    confidence_signals: dict[str, Any]
    grounding: GroundingOut
    identity: IdentitySummary
    timings_ms: dict[str, int]
    usage: UsageOut
    debug: dict[str, Any] | None = None
