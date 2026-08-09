"""Reciprocal Rank Fusion.

Combining two ranked lists sounds like it should be a weighted sum of scores.
It should not, and the reason is worth stating precisely: the two scores are
not comparable and never will be.

Cosine similarity lives in [-1, 1] and, for a decent embedding model on real
text, clusters tightly in roughly [0.55, 0.90]. `ts_rank_cd` is unbounded
below 1, corpus-dependent, and shifts as documents are added. Any weighted sum
needs a normalisation step, and every normalisation scheme - min-max, z-score,
softmax - is unstable in the case you most need it to be stable: when one
retriever returns nothing relevant, its scores get stretched to fill [0, 1]
and garbage is promoted to the top.

RRF sidesteps this by throwing the scores away and using only positions:

    RRF(d) = sum over retrievers of  1 / (k + rank_r(d))

Ranks are comparable by construction. The constant k (60 is the value from the
original paper and the field standard) damps the head of each list, so that a
document ranked 3rd by *both* retrievers beats one ranked 1st by one and 200th
by the other. That is almost always the right call: agreement across two
methods that fail differently is strong evidence, and a single method's top
hit is weak evidence.

Worked example, k=60:
    ranked 1st by keyword only    -> 1/61            = 0.0164
    ranked 3rd by both            -> 1/63 + 1/63     = 0.0317   <- wins
    ranked 1st and 200th          -> 1/61 + 1/260    = 0.0203
"""

from __future__ import annotations

import uuid

from app.retrieval.types import Candidate

#: The damping constant from Cormack et al. Larger flattens the contribution of
#: top ranks; smaller makes first place dominate. 60 is the standard default
#: and there is no reason to deviate without an evaluation showing a gain.
DEFAULT_RRF_K = 60


def reciprocal_rank_fusion(
    *result_lists: list[Candidate],
    k: int = DEFAULT_RRF_K,
    limit: int | None = None,
) -> list[Candidate]:
    """Fuse ranked candidate lists into one, ordered by RRF score.

    Candidates found by more than one retriever are merged into a single
    object that keeps every retriever's rank and score, so the debug payload
    can answer "who found this, and where did they put it?".

    Note: this **mutates** the candidates it is given, writing `rrf_score` and
    the absorbed ranks onto them. That is deliberate - a candidate accumulates
    its provenance as it moves down the pipeline - but it means calling this
    twice over the same list overwrites the first call's scores.
    """
    if k < 1:
        raise ValueError("RRF k must be >= 1")

    merged: dict[uuid.UUID, Candidate] = {}
    scores: dict[uuid.UUID, float] = {}

    for results in result_lists:
        for position, candidate in enumerate(results, start=1):
            chunk_id = candidate.chunk_id
            existing = merged.get(chunk_id)
            if existing is None:
                merged[chunk_id] = candidate
            else:
                _absorb(existing, candidate)
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + position)

    for chunk_id, score in scores.items():
        merged[chunk_id].rrf_score = score

    ordered = sorted(
        merged.values(),
        # chunk_id breaks ties deterministically: two candidates with identical
        # RRF scores must not swap order between runs, or the evaluation
        # harness measures noise.
        key=lambda c: (-(c.rrf_score or 0.0), str(c.chunk_id)),
    )
    return ordered[:limit] if limit is not None else ordered


def _absorb(target: Candidate, other: Candidate) -> None:
    """Fold a duplicate hit's provenance into the candidate we are keeping."""
    if other.keyword_rank is not None:
        target.keyword_rank = other.keyword_rank
        target.keyword_score = other.keyword_score
    if other.vector_rank is not None:
        target.vector_rank = other.vector_rank
        target.vector_score = other.vector_score
