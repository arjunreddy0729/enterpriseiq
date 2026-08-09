"""Retrieval and answer metrics, checked against hand-computed values.

A benchmark is only worth quoting if its arithmetic is verifiable. Every
expected value below is derived from the definition in the docstring of the
function under test, not from running the code and recording what came out.
"""

from __future__ import annotations

import math

import pytest

from app.evaluation.metrics import (
    citation_precision,
    dcg_at_k,
    fact_coverage,
    mean,
    ndcg_at_k,
    percentile,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)

A, B, C, D = "a.md", "b.md", "c.md", "d.md"


# ---------------------------------------------------------------------------
# Recall@k
# ---------------------------------------------------------------------------
def test_recall_finds_the_only_relevant_document() -> None:
    assert recall_at_k([A, B, C], [A], k=3) == 1.0


def test_recall_is_zero_when_nothing_relevant_is_retrieved() -> None:
    assert recall_at_k([B, C], [A], k=3) == 0.0


def test_recall_respects_the_cutoff() -> None:
    # A is at position 3, so it is outside k=2.
    assert recall_at_k([B, C, A], [A], k=2) == 0.0
    assert recall_at_k([B, C, A], [A], k=3) == 1.0


def test_recall_with_multiple_relevant_documents() -> None:
    # One of two found -> 0.5
    assert recall_at_k([A, C], [A, B], k=2) == 0.5


def test_recall_with_no_relevant_documents_is_zero_not_an_error() -> None:
    assert recall_at_k([A], [], k=5) == 0.0


# ---------------------------------------------------------------------------
# Precision@k
# ---------------------------------------------------------------------------
def test_precision_divides_by_k_not_by_results_returned() -> None:
    """Returning 1 correct result out of 1 must not beat 1 correct out of 5
    when 5 were requested - otherwise a system is rewarded for returning less."""
    assert precision_at_k([A], [A], k=5) == pytest.approx(0.2)
    assert precision_at_k([A, B, C, D, "e.md"], [A], k=5) == pytest.approx(0.2)


def test_precision_all_relevant() -> None:
    assert precision_at_k([A, B], [A, B], k=2) == 1.0


def test_precision_with_zero_k() -> None:
    assert precision_at_k([A], [A], k=0) == 0.0


# ---------------------------------------------------------------------------
# Reciprocal rank / MRR
# ---------------------------------------------------------------------------
def test_reciprocal_rank_first_position() -> None:
    assert reciprocal_rank([A, B], [A]) == 1.0


def test_reciprocal_rank_second_position() -> None:
    assert reciprocal_rank([B, A], [A]) == 0.5


def test_reciprocal_rank_fourth_position() -> None:
    assert reciprocal_rank([B, C, D, A], [A]) == 0.25


def test_reciprocal_rank_absent() -> None:
    assert reciprocal_rank([B, C], [A]) == 0.0


def test_reciprocal_rank_uses_the_first_hit_only() -> None:
    assert reciprocal_rank([B, A, C], [A, C]) == 0.5


# ---------------------------------------------------------------------------
# DCG / nDCG - the arithmetic worth checking by hand
# ---------------------------------------------------------------------------
def test_dcg_matches_the_definition() -> None:
    # DCG@3 for gains [1, 0, 1] = 1/log2(2) + 0/log2(3) + 1/log2(4)
    #                           = 1.0 + 0 + 0.5 = 1.5
    assert dcg_at_k([1.0, 0.0, 1.0], 3) == pytest.approx(1.5)


def test_ndcg_perfect_ranking_is_one() -> None:
    assert ndcg_at_k([A, B, C], [A], k=3) == 1.0


def test_ndcg_penalises_a_lower_position() -> None:
    # gains [0,1,0] -> DCG = 1/log2(3) = 0.63093; IDCG = 1
    assert ndcg_at_k([B, A, C], [A], k=3) == pytest.approx(1 / math.log2(3))


def test_ndcg_is_normalised_across_different_relevant_set_sizes() -> None:
    """A two-source question ranked perfectly must score the same 1.0 as a
    one-source question ranked perfectly, or averaging across a mixed
    benchmark silently weights question types."""
    assert ndcg_at_k([A, B, C], [A, B], k=3) == pytest.approx(1.0)
    assert ndcg_at_k([A, B, C], [A], k=3) == pytest.approx(1.0)


def test_ndcg_partial_credit() -> None:
    # relevant {A, B}; retrieved [A, C, B]
    # DCG  = 1/log2(2) + 0 + 1/log2(4) = 1 + 0.5 = 1.5
    # IDCG = 1/log2(2) + 1/log2(3)     = 1 + 0.63093 = 1.63093
    expected = 1.5 / (1 + 1 / math.log2(3))
    assert ndcg_at_k([A, C, B], [A, B], k=3) == pytest.approx(expected)


def test_ndcg_zero_when_nothing_relevant_retrieved() -> None:
    assert ndcg_at_k([C, D], [A], k=2) == 0.0


# ---------------------------------------------------------------------------
# Citation precision
# ---------------------------------------------------------------------------
def test_citation_precision_all_correct() -> None:
    assert citation_precision([A], [A, B]) == 1.0


def test_citation_precision_half_wrong() -> None:
    assert citation_precision([A, C], [A, B]) == 0.5


def test_citing_nothing_scores_zero() -> None:
    """An answer that cites nothing is not vacuously perfect - it is
    unverifiable, which is the thing this metric exists to penalise."""
    assert citation_precision([], [A]) == 0.0


# ---------------------------------------------------------------------------
# Fact coverage
# ---------------------------------------------------------------------------
def test_fact_coverage_all_present() -> None:
    assert fact_coverage("The cap is $85 per day.", ["$85", "day"]) == 1.0


def test_fact_coverage_partial() -> None:
    assert fact_coverage("The cap is $85.", ["$85", "per day"]) == 0.5


def test_fact_coverage_alternatives() -> None:
    assert fact_coverage("Tokens last one hour.", ["3600|1 hour|one hour"]) == 1.0


def test_fact_coverage_is_case_insensitive() -> None:
    assert fact_coverage("OAUTH 2.0 CLIENT CREDENTIALS", ["oauth 2.0"]) == 1.0


def test_fact_coverage_normalises_whitespace() -> None:
    assert fact_coverage("uses   OAuth 2.0\nfor auth", ["OAuth 2.0"]) == 1.0


def test_no_expected_facts_is_vacuously_covered() -> None:
    assert fact_coverage("anything", []) == 1.0


def test_fact_coverage_detects_a_wrong_number() -> None:
    """The case embeddings are worst at and this check is best at."""
    assert fact_coverage("The cap is $75 per day.", ["$85"]) == 0.0


# ---------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------
def test_percentile_nearest_rank() -> None:
    values = [10, 20, 30, 40, 50]
    assert percentile(values, 50) == 30
    assert percentile(values, 100) == 50
    assert percentile(values, 1) == 10


def test_percentile_of_empty_is_zero() -> None:
    assert percentile([], 95) == 0.0


def test_mean() -> None:
    assert mean([1.0, 2.0, 3.0]) == 2.0
    assert mean([]) == 0.0
