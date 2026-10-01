"""Request and response models for /api/v1/search."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.retrieval.types import Candidate, Filters


class SearchFilters(BaseModel):
    """Optional metadata narrowing. Access groups are NOT here - they come
    from the authenticated identity and can never be supplied by the caller."""

    model_config = ConfigDict(extra="forbid")

    departments: list[str] = Field(default_factory=list)
    doc_types: list[str] = Field(default_factory=list)
    classifications: list[str] = Field(default_factory=list)
    updated_after: dt.date | None = None
    updated_before: dt.date | None = None

    def to_domain(self) -> Filters:
        return Filters(
            departments=tuple(self.departments),
            doc_types=tuple(self.doc_types),
            classifications=tuple(self.classifications),
            updated_after=self.updated_after,
            updated_before=self.updated_before,
        )


class SearchRequest(BaseModel):
    # The example is what /docs pre-fills. Without it Swagger generates
    # placeholder filters ("departments": ["string"]) that match nothing.
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"query": "What are the bonus targets by level?"}]},
    )

    query: str = Field(min_length=1, max_length=1000)
    filters: SearchFilters | None = None
    top_k: int = Field(default=10, ge=1, le=50)
    include_debug: bool = False


class RetrievalScores(BaseModel):
    """Every score and rank that contributed, kept separate.

    Collapsing these into one number would make a bad result impossible to
    diagnose: "which retriever found this, and where did it rank it?" is the
    first question worth asking, and it needs both retrievers' positions.
    """

    keyword_rank: int | None = None
    keyword_score: float | None = None
    vector_rank: int | None = None
    vector_score: float | None = None
    rrf_score: float | None = None
    rerank_score: float | None = None
    retrieved_by: list[str] = Field(default_factory=list)


class SearchResult(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    section_path: str | None
    source_uri: str
    department: str | None
    doc_type: str | None
    classification: str | None
    chunk_index: int
    page_from: int | None = None
    page_to: int | None = None
    content: str
    scores: RetrievalScores

    @classmethod
    def from_candidate(cls, candidate: Candidate) -> SearchResult:
        return cls(
            chunk_id=candidate.chunk_id,
            document_id=candidate.document_id,
            document_title=candidate.document_title,
            section_path=candidate.section_path,
            source_uri=candidate.source_uri,
            department=candidate.department,
            doc_type=candidate.doc_type,
            classification=candidate.classification,
            chunk_index=candidate.chunk_index,
            page_from=candidate.page_from,
            page_to=candidate.page_to,
            content=candidate.content,
            scores=RetrievalScores(
                keyword_rank=candidate.keyword_rank,
                keyword_score=candidate.keyword_score,
                vector_rank=candidate.vector_rank,
                vector_score=candidate.vector_score,
                rrf_score=candidate.rrf_score,
                rerank_score=candidate.rerank_score,
                retrieved_by=list(candidate.retrieved_by),
            ),
        )


class IdentitySummary(BaseModel):
    """Echoed back so it is obvious which permissions produced these results."""

    email: str
    name: str
    groups: list[str]


class SearchDebug(BaseModel):
    keyword_candidates: int
    vector_candidates: int
    fused_candidates: int
    reranked: bool
    timings_ms: dict[str, int]
    filters: dict[str, object]
    tsquery: str | None = None


class SearchResponse(BaseModel):
    request_id: str
    query: str
    identity: IdentitySummary
    result_count: int
    results: list[SearchResult]
    took_ms: int
    debug: SearchDebug | None = None
