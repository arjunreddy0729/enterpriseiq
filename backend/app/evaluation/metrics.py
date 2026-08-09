"""Retrieval and answer metrics, implemented rather than approximated.

Every function here is a real calculation with a stated definition, because a
benchmark whose numbers cannot be reproduced from first principles is worse
than no benchmark: it produces a résumé bullet you cannot defend in an
interview.

All retrieval metrics work at **document** granularity. A question is answered
by a document, not by chunk #7 of it, and scoring at chunk level would reward
a system for retrieving four chunks of the right document over one chunk each
of the right document and a wrong one.
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def recall_at_k(retrieved: Sequence[str], relevant: Sequence[str], k: int) -> float:
    """Fraction of the relevant documents that appear in the top k.

        recall@k = |relevant ∩ retrieved[:k]| / |relevant|

    The headline retrieval number: if the right document is not here, no amount
    of reranking or prompting downstream can recover it.
    """
    if not relevant:
        return 0.0
    top = set(retrieved[:k])
    return len(top & set(relevant)) / len(set(relevant))


def precision_at_k(retrieved: Sequence[str], relevant: Sequence[str], k: int) -> float:
    """Fraction of the top k that are relevant.

        precision@k = |relevant ∩ retrieved[:k]| / k

    Divided by k, not by the number retrieved: returning 3 results when 10 were
    asked for should not score better than returning 10 with the same 3 hits.
    """
    if k <= 0:
        return 0.0
    top = retrieved[:k]
    return len(set(top) & set(relevant)) / k


def reciprocal_rank(retrieved: Sequence[str], relevant: Sequence[str]) -> float:
    """1 / rank of the first relevant document, or 0 if none appears.

    Averaged over a benchmark this is MRR. It answers "how far down the list
    does the user have to read?" - and unlike recall it is sensitive to whether
    the right answer is 1st or 8th.
    """
    relevant_set = set(relevant)
    for position, document in enumerate(retrieved, start=1):
        if document in relevant_set:
            return 1.0 / position
    return 0.0


def dcg_at_k(gains: Sequence[float], k: int) -> float:
    """Discounted cumulative gain.

        DCG@k = Σ  gain_i / log2(i + 1)      for i = 1..k

    The log discount encodes that position 1 matters much more than position 8.
    """
    return sum(gain / math.log2(index + 1) for index, gain in enumerate(gains[:k], start=1))


def ndcg_at_k(retrieved: Sequence[str], relevant: Sequence[str], k: int) -> float:
    """nDCG@k with binary relevance: DCG divided by the best achievable DCG.

    Normalising matters when questions have different numbers of correct
    sources - a multi-hop question with two relevant documents cannot reach the
    same raw DCG as a factoid with one, so averaging raw DCG across a mixed
    benchmark would silently weight question types.
    """
    if not relevant:
        return 0.0
    relevant_set = set(relevant)
    gains = [1.0 if document in relevant_set else 0.0 for document in retrieved]
    ideal = [1.0] * min(len(relevant_set), k)

    ideal_dcg = dcg_at_k(ideal, k)
    if ideal_dcg == 0:
        return 0.0
    return dcg_at_k(gains, k) / ideal_dcg


def citation_precision(cited: Sequence[str], relevant: Sequence[str]) -> float:
    """Fraction of cited documents that were actually the right ones.

    Distinct from retrieval precision: this scores what the answer *used*, not
    what the system *found*. An answer that retrieves the right document and
    then cites a different one is wrong in a way retrieval metrics cannot see.
    """
    if not cited:
        return 0.0
    return len(set(cited) & set(relevant)) / len(set(cited))


def fact_coverage(answer: str, expected_facts: Sequence[str]) -> float:
    """Fraction of the expected facts present in the answer.

    Substring matching over normalised text, with '|' marking acceptable
    alternatives ("3600|1 hour"). This is deliberately a *coverage* check on
    specific values, not a similarity score against a reference answer:
    "$85" either appears or it does not, and that is the thing worth measuring.
    It cannot detect an answer that states the right number inside a wrong
    claim - that is what grounding verification and the LLM judge are for.
    """
    if not expected_facts:
        return 1.0
    normalised = " ".join(answer.lower().split())
    hits = 0
    for expectation in expected_facts:
        alternatives = [a.strip().lower() for a in expectation.split("|") if a.strip()]
        if any(alternative in normalised for alternative in alternatives):
            hits += 1
    return hits / len(expected_facts)


def percentile(values: Sequence[float], p: float) -> float:
    """Nearest-rank percentile. p is 0-100."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if p <= 0:
        return ordered[0]
    index = math.ceil(p / 100 * len(ordered)) - 1
    return ordered[max(0, min(index, len(ordered) - 1))]


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0
