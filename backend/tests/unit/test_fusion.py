"""Reciprocal Rank Fusion.

Pure arithmetic over ranks, so this needs no database and no model.
"""

from __future__ import annotations

import uuid

import pytest

from app.retrieval.fusion import DEFAULT_RRF_K, reciprocal_rank_fusion
from app.retrieval.types import Candidate


def candidate(name: str) -> Candidate:
    """A candidate with a stable id derived from its name."""
    return Candidate(
        chunk_id=uuid.uuid5(uuid.NAMESPACE_DNS, name),
        document_id=uuid.uuid5(uuid.NAMESPACE_DNS, f"doc-{name}"),
        content=name,
        embed_text=name,
        section_path=None,
        document_title=name,
        source_uri=f"{name}.md",
        department=None,
        doc_type=None,
        classification=None,
        chunk_index=0,
    )


def ranked(*names: str, keyword: bool) -> list[Candidate]:
    out = []
    for position, name in enumerate(names, start=1):
        c = candidate(name)
        if keyword:
            c.keyword_rank, c.keyword_score = position, 1.0 / position
        else:
            c.vector_rank, c.vector_score = position, 1.0 / position
        out.append(c)
    return out


def test_agreement_beats_a_single_first_place() -> None:
    """The central property: two retrievers agreeing at rank 3 outranks one
    retriever's rank 1. Agreement across methods that fail differently is
    stronger evidence than one method's top hit."""
    keyword = ranked("solo", "x", "both", keyword=True)
    vector = ranked("y", "z", "both", keyword=False)

    fused = reciprocal_rank_fusion(keyword, vector)
    assert fused[0].content == "both"


def test_worked_example_from_the_docstring() -> None:
    keyword = ranked("a", keyword=True)
    fused = reciprocal_rank_fusion(keyword, [])
    assert fused[0].rrf_score == pytest.approx(1 / (DEFAULT_RRF_K + 1))


def test_scores_add_across_retrievers() -> None:
    keyword = ranked("shared", keyword=True)
    vector = ranked("shared", keyword=False)
    fused = reciprocal_rank_fusion(keyword, vector)
    assert len(fused) == 1
    expected = 1 / (DEFAULT_RRF_K + 1) * 2
    assert fused[0].rrf_score == pytest.approx(expected)


def test_duplicate_keeps_both_provenances() -> None:
    """A chunk found twice must remember where each retriever placed it."""
    fused = reciprocal_rank_fusion(
        ranked("x", "shared", keyword=True), ranked("shared", keyword=False)
    )
    shared = next(c for c in fused if c.content == "shared")
    assert shared.keyword_rank == 2
    assert shared.vector_rank == 1
    assert set(shared.retrieved_by) == {"keyword", "vector"}


def test_rank_not_score_decides() -> None:
    """Raw scores must not influence the outcome - only positions do.

    This is the reason RRF exists: cosine similarity and ts_rank_cd are not
    comparable quantities, so any score-based fusion needs a normalisation
    step that breaks down exactly when one retriever returns garbage.
    """
    keyword = ranked("first", "second", keyword=True)
    for c in keyword:
        c.keyword_score = 999.0  # absurd scores, unchanged ranks

    fused = reciprocal_rank_fusion(keyword, [])
    assert [c.content for c in fused] == ["first", "second"]


def test_limit_truncates() -> None:
    fused = reciprocal_rank_fusion(ranked("a", "b", "c", "d", keyword=True), limit=2)
    assert len(fused) == 2


def test_empty_inputs() -> None:
    assert reciprocal_rank_fusion([], []) == []


def test_single_list_preserves_order() -> None:
    fused = reciprocal_rank_fusion(ranked("a", "b", "c", keyword=True))
    assert [c.content for c in fused] == ["a", "b", "c"]


def test_ties_break_deterministically() -> None:
    """Equal RRF scores must not reorder between runs, or the evaluation
    harness measures noise instead of retrieval quality."""
    first = reciprocal_rank_fusion(ranked("a", keyword=True), ranked("b", keyword=False))
    second = reciprocal_rank_fusion(ranked("a", keyword=True), ranked("b", keyword=False))
    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]


def test_k_must_be_positive() -> None:
    with pytest.raises(ValueError):
        reciprocal_rank_fusion(ranked("a", keyword=True), k=0)


def test_larger_k_flattens_the_head() -> None:
    """k damps the advantage of top ranks; that is its whole purpose.

    Note the two fresh lists: fusion writes rrf_score onto the candidates it
    is given, so reusing one list across both calls would have the second run
    overwrite the first run's scores.
    """
    small = reciprocal_rank_fusion(ranked("first", "second", keyword=True), k=1)
    large = reciprocal_rank_fusion(ranked("first", "second", keyword=True), k=1000)

    small_gap = small[0].rrf_score - small[1].rrf_score
    large_gap = large[0].rrf_score - large[1].rrf_score
    assert large_gap < small_gap
