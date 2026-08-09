"""Reranker contract and failure behaviour.

The model itself is exercised by the benchmark, not here. What these tests
pin down is the contract every caller depends on - and specifically that a
broken reranker degrades the ranking rather than failing the request.
"""

from __future__ import annotations

from typing import Any

from app.retrieval.reranker import BGEReranker, IdentityReranker
from tests.unit.test_citations import candidate


def candidates(n: int) -> list[Any]:
    out = []
    for i in range(n):
        c = candidate(f"doc{i}")
        c.rrf_score = 1.0 / (i + 1)  # fused order: doc0 best
        out.append(c)
    return out


class _ExplodingModel:
    def predict(self, *_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("model blew up mid-scoring")


class _ScriptedModel:
    """Scores in reverse, so a working reranker visibly inverts the order."""

    def __init__(self, scores: list[float]) -> None:
        self.scores = scores

    def predict(self, pairs: list[Any], **_kwargs: Any) -> list[float]:
        return self.scores[: len(pairs)]


def test_identity_reranker_preserves_order() -> None:
    items = candidates(5)
    result = IdentityReranker().rerank("q", items, top_n=3)
    assert [c.source_uri for c in result] == ["doc0.md", "doc1.md", "doc2.md"]


def test_reranker_reorders_by_score() -> None:
    reranker = BGEReranker()
    reranker._model = _ScriptedModel([0.1, 0.9, 0.5])  # doc1 best
    result = reranker.rerank("q", candidates(3), top_n=3)
    assert [c.source_uri for c in result] == ["doc1.md", "doc2.md", "doc0.md"]


def test_scores_are_recorded_on_the_candidates() -> None:
    reranker = BGEReranker()
    reranker._model = _ScriptedModel([0.1, 0.9])
    result = reranker.rerank("q", candidates(2), top_n=2)
    assert all(c.rerank_score is not None for c in result)


def test_rerank_score_becomes_the_final_score() -> None:
    reranker = BGEReranker()
    reranker._model = _ScriptedModel([0.7, 0.2])
    top = reranker.rerank("q", candidates(2), top_n=1)[0]
    assert top.final_score == top.rerank_score


def test_top_n_truncates() -> None:
    reranker = BGEReranker()
    reranker._model = _ScriptedModel([0.1, 0.2, 0.3, 0.4, 0.5])
    assert len(reranker.rerank("q", candidates(5), top_n=2)) == 2


def test_scoring_failure_falls_back_to_the_fused_order() -> None:
    """A degraded ranking beats a failed request. The fused order is a
    perfectly serviceable ranking on its own."""
    reranker = BGEReranker()
    reranker._model = _ExplodingModel()
    result = reranker.rerank("q", candidates(4), top_n=3)
    assert [c.source_uri for c in result] == ["doc0.md", "doc1.md", "doc2.md"]


def test_load_failure_falls_back_and_is_not_retried() -> None:
    reranker = BGEReranker(model_name="does-not-exist/nope")
    first = reranker.rerank("q", candidates(3), top_n=2)
    assert [c.source_uri for c in first] == ["doc0.md", "doc1.md"]
    assert reranker._failed, "a broken model must not be reloaded on every request"

    second = reranker.rerank("q", candidates(3), top_n=2)
    assert [c.source_uri for c in second] == ["doc0.md", "doc1.md"]


def test_empty_input() -> None:
    assert BGEReranker().rerank("q", [], top_n=5) == []


def test_ties_break_deterministically() -> None:
    """Equal scores must not reorder between runs, or the benchmark measures
    sort instability instead of the model."""
    reranker = BGEReranker()
    reranker._model = _ScriptedModel([0.5, 0.5, 0.5])
    first = [c.chunk_id for c in reranker.rerank("q", candidates(3), top_n=3)]

    reranker2 = BGEReranker()
    reranker2._model = _ScriptedModel([0.5, 0.5, 0.5])
    second = [c.chunk_id for c in reranker2.rerank("q", candidates(3), top_n=3)]

    assert first == second
