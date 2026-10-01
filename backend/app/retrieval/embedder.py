"""Local BGE embeddings.

Runs on the CPU, costs nothing, and needs no network after the first download.
That is not just a budget decision: you will re-embed this corpus many times
while tuning chunk sizes, and a per-token bill on every iteration is a strong
incentive to stop tuning.

The one detail that is easy to get wrong and expensive to miss: BGE is an
**asymmetric** model. It was trained with an instruction prefix on queries and
no prefix on documents. Embedding both sides the same way costs several points
of retrieval quality, and it fails silently - the system still returns results,
they are just worse. `embed_documents` and `embed_query` are separate methods
so the two paths cannot be confused.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

import numpy as np

from app.core.config import get_settings
from app.core.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover
    from sentence_transformers import SentenceTransformer

logger = get_logger(__name__)


class BGEEmbedder:
    """Sentence-Transformers embedder with lazy, thread-safe model loading."""

    def __init__(
        self,
        model_name: str | None = None,
        dimension: int | None = None,
        query_prefix: str | None = None,
        batch_size: int | None = None,
    ) -> None:
        settings = get_settings()
        self._model_name = model_name or settings.embedding_model
        self._dimension = dimension or settings.embedding_dim
        self._query_prefix = (
            settings.embedding_query_prefix if query_prefix is None else query_prefix
        )
        self._batch_size = batch_size or settings.embedding_batch_size
        self._model: SentenceTransformer | None = None
        # Loading takes seconds and allocates hundreds of MB. Under uvicorn's
        # threadpool several requests can race into the first call at once.
        self._lock = threading.Lock()

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def query_prefix(self) -> str:
        return self._query_prefix

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def _load(self) -> SentenceTransformer:
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:  # another thread won the race
                return self._model
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # pragma: no cover - optional extra
                raise RuntimeError("Embeddings need the 'ml' extra: pip install '.[ml]'") from exc

            logger.info("embedder_loading", model=self._model_name)
            model = SentenceTransformer(self._model_name, device="cpu")

            actual = model.get_sentence_embedding_dimension()
            if actual != self._dimension:
                # Failing here beats writing wrong-width vectors into a column
                # that will reject them one row at a time.
                raise RuntimeError(
                    f"{self._model_name} produces {actual}-dimensional vectors but "
                    f"EMBEDDING_DIM is {self._dimension}. Fix .env and re-index."
                )
            self._model = model
            logger.info("embedder_loaded", model=self._model_name, dimension=actual)
            return model

    # -- encoding ----------------------------------------------------------
    def embed_documents(self, texts: list[str]) -> np.ndarray:
        """Embed passages. No prefix - that is the query side only."""
        if not texts:
            return np.empty((0, self._dimension), dtype=np.float32)
        return self._encode(texts)

    def embed_query(self, text: str) -> np.ndarray:
        """Embed one query, with the BGE instruction prefix applied."""
        return self._encode([f"{self._query_prefix}{text}"])[0]

    def embed_queries(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self._dimension), dtype=np.float32)
        return self._encode([f"{self._query_prefix}{t}" for t in texts])

    def _encode(self, texts: list[str]) -> np.ndarray:
        model = self._load()
        vectors = model.encode(
            texts,
            batch_size=self._batch_size,
            # L2-normalise so that cosine similarity and inner product agree,
            # and so pgvector's <=> distance maps cleanly to 1 - similarity.
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return np.asarray(vectors, dtype=np.float32)


class DeterministicEmbedder:
    """A fake embedder for tests. Never used in the running system.

    Hashes text into a stable pseudo-random unit vector. Nearest-neighbour
    results are meaningless, which is the point: tests that use this are
    testing plumbing, permissions and SQL, not retrieval quality. Anything
    claiming to measure retrieval quality must use the real model.
    """

    def __init__(self, dimension: int | None = None) -> None:
        self._dimension = dimension or get_settings().embedding_dim

    @property
    def model_name(self) -> str:
        return "deterministic-test-embedder"

    @property
    def dimension(self) -> int:
        return self._dimension

    def _vector(self, text: str) -> np.ndarray:
        seed = abs(hash(text)) % (2**32)
        rng = np.random.default_rng(seed)
        vector = rng.standard_normal(self._dimension).astype(np.float32)
        return vector / np.linalg.norm(vector)

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self._dimension), dtype=np.float32)
        return np.vstack([self._vector(t) for t in texts])

    def embed_query(self, text: str) -> np.ndarray:
        return self._vector(text)


_default: Any = None


def get_embedder() -> Any:
    """Process-wide embedder. One model load per process, not per request."""
    global _default
    if _default is None:
        _default = BGEEmbedder()
    return _default
