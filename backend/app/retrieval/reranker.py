"""Cross-encoder reranking.

The bi-encoder used for retrieval embeds the query and the passage
*independently* - that is what makes approximate nearest-neighbour search
possible at all, because passage vectors can be computed once at ingest time
and indexed. The cost is that the model never sees the two together, so it
scores topical similarity rather than "does this passage answer this
question".

A cross-encoder concatenates query and passage into one sequence and runs full
attention across both. It can tell that a passage mentioning OAuth is about
*configuring* OAuth rather than *authenticating with* it. That is far more
accurate and O(n) forward passes, so it can only run on a shortlist - which is
exactly the retrieve-then-rerank shape: cheap retrievers buy recall, the
expensive model buys precision.

**Failure policy.** If the model fails to load or scoring raises, this returns
the fused order truncated to top_n rather than propagating the error. A
degraded ranking is a worse answer; a failed request is no answer at all, and
the fused order is a perfectly serviceable ranking on its own.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from app.core.config import get_settings
from app.core.logging import get_logger
from app.retrieval.types import Candidate

if TYPE_CHECKING:  # pragma: no cover
    from sentence_transformers import CrossEncoder

logger = get_logger(__name__)


class BGEReranker:
    """Local cross-encoder reranker. CPU, no network after first download."""

    def __init__(
        self,
        model_name: str | None = None,
        batch_size: int = 16,
        max_length: int = 512,
    ) -> None:
        settings = get_settings()
        self._model_name = model_name or settings.reranker_model
        self._batch_size = batch_size
        #: Query + passage must fit in one sequence. Chunks run to ~700 tokens,
        #: so truncation is real - the model sees the head of a long passage.
        #: That is the standard trade and the reason chunks are kept modest.
        self._max_length = max_length
        self._model: CrossEncoder | None = None
        self._lock = threading.Lock()
        self._failed = False

    @property
    def model_name(self) -> str:
        return self._model_name

    def _load(self) -> CrossEncoder | None:
        if self._model is not None:
            return self._model
        if self._failed:
            return None
        with self._lock:
            if self._model is not None:
                return self._model
            try:
                from sentence_transformers import CrossEncoder

                logger.info("reranker_loading", model=self._model_name)
                self._model = CrossEncoder(
                    self._model_name, max_length=self._max_length, device="cpu"
                )
                logger.info("reranker_loaded", model=self._model_name)
            except Exception as exc:
                # Remembered, so a broken model is not retried on every request.
                self._failed = True
                logger.error("reranker_load_failed", model=self._model_name, error=str(exc))
                return None
            return self._model

    def rerank(self, query: str, candidates: list[Candidate], top_n: int) -> list[Candidate]:
        if not candidates:
            return []

        model = self._load()
        if model is None:
            logger.warning("reranker_unavailable_using_fused_order")
            return candidates[:top_n]

        # Score against embed_text, not content: it carries the heading trail,
        # which is often what disambiguates two similar passages.
        # Typed loosely: predict()'s input type differs across library versions.
        pairs: list[Any] = [(query, candidate.embed_text) for candidate in candidates]

        try:
            scores: Any = model.predict(pairs, batch_size=self._batch_size, show_progress_bar=False)
        except Exception as exc:
            logger.error("reranker_scoring_failed", error=str(exc))
            return candidates[:top_n]

        for candidate, score in zip(candidates, scores, strict=True):
            candidate.rerank_score = float(score)

        ordered = sorted(
            candidates,
            # chunk_id breaks ties deterministically so repeated benchmark runs
            # measure the system rather than sort instability.
            key=lambda c: (-(c.rerank_score or 0.0), str(c.chunk_id)),
        )
        return ordered[:top_n]


class IdentityReranker:
    """Passes the fused order through unchanged.

    Used to prove that the benchmark harness itself does not change results -
    a run with this reranker must score identically to a run with none.
    """

    @property
    def model_name(self) -> str:
        return "identity"

    def rerank(self, query: str, candidates: list[Candidate], top_n: int) -> list[Candidate]:
        return candidates[:top_n]


_default: BGEReranker | None = None


def get_reranker() -> BGEReranker:
    """Process-wide reranker. One model load per process."""
    global _default
    if _default is None:
        _default = BGEReranker()
    return _default
