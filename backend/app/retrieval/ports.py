"""The interfaces that let this system change its mind later.

Four seams. Everything above them is written once:

    Embedder  - swap BGE for a hosted embedding API, or a different local model
    Retriever - swap PostgreSQL for OpenSearch when the corpus outgrows it
    Reranker  - swap the local cross-encoder for a hosted reranking model
    LLMClient - swap Anthropic for another provider

The point is not that any of these swaps are planned. It is that "how would
you scale this to millions of documents?" has a concrete answer - write one
new Retriever - rather than an architectural one.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np

from app.retrieval.types import Candidate, RetrievalQuery


@runtime_checkable
class Embedder(Protocol):
    """Turns text into vectors.

    Documents and queries go through different methods on purpose. Asymmetric
    embedding models - BGE among them - are trained with an instruction prefix
    on the query side only, and applying it to documents (or omitting it from
    queries) measurably degrades retrieval. Two methods make that impossible to
    get wrong by accident.
    """

    @property
    def model_name(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    def embed_documents(self, texts: list[str]) -> np.ndarray: ...

    def embed_query(self, text: str) -> np.ndarray: ...


@runtime_checkable
class Retriever(Protocol):
    """Finds candidate chunks for a query.

    Takes a RetrievalQuery, which cannot be built without access groups, so an
    implementation physically cannot run an unfiltered search.
    """

    @property
    def kind(self) -> str: ...

    def search(self, query: RetrievalQuery) -> list[Candidate]: ...


@runtime_checkable
class Reranker(Protocol):
    """Reorders candidates with a model that sees query and passage together."""

    @property
    def model_name(self) -> str: ...

    def rerank(
        self, query: str, candidates: list[Candidate], top_n: int
    ) -> list[Candidate]: ...
