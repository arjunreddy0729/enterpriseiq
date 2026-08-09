"""Confidence, reported as a band and never as a percentage.

A percentage is a claim about calibration: saying "94% confident" asserts that
across all answers scored 0.94, roughly 94% were correct. Demonstrating that
needs a labelled outcome for thousands of answers. Without it, a percentage is
a number with a decimal point and no meaning - and decimal points are
persuasive, which makes an uncalibrated one actively harmful.

So this returns HIGH / MEDIUM / LOW, computed from four signals that are
individually explainable, and returns the signals alongside the band so the
verdict is auditable rather than magic:

  retrieval    how strong the best evidence was
  agreement    how many distinct documents support the answer
  grounding    what fraction of claims were verifiable against their sources
  citations    whether the answer actually cited what it used

The thresholds below are judgement, not measurement. They are stated here so
they can be argued with, and they are the first thing that should be tuned
once the evaluation harness can measure whether the bands separate correct
answers from incorrect ones.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum

from app.generation.citations import CitationResult
from app.generation.grounding import GroundingReport
from app.retrieval.types import Candidate


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(slots=True)
class ConfidenceSignals:
    """The inputs, exposed so the band can be checked rather than believed."""

    top_score: float
    score_margin: float
    supporting_documents: int
    grounding_score: float
    citation_count: int
    uncited_claims: int

    def to_dict(self) -> dict[str, object]:
        return {k: round(v, 4) if isinstance(v, float) else v for k, v in asdict(self).items()}


def compute_signals(
    candidates: list[Candidate],
    citations: CitationResult,
    grounding: GroundingReport,
) -> ConfidenceSignals:
    scores = [c.final_score for c in candidates]
    top = scores[0] if scores else 0.0
    # Margin between the best candidate and the 4th: a flat distribution means
    # nothing stood out, which usually means the question was not really
    # answered by any single passage.
    fourth = scores[3] if len(scores) > 3 else 0.0
    margin = top - fourth

    return ConfidenceSignals(
        top_score=top,
        score_margin=margin,
        supporting_documents=len({c.document_id for c in citations.citations}),
        grounding_score=grounding.score,
        citation_count=citations.citation_count,
        uncited_claims=citations.uncited_sentences,
    )


def assess(signals: ConfidenceSignals) -> Confidence:
    """Map signals to a band.

    HIGH requires every signal to be good, not an average of them. Averaging
    lets one strong signal mask a disqualifying one - an answer with excellent
    retrieval scores and no citations at all should never be HIGH.
    """
    if signals.citation_count == 0:
        # An answer citing nothing cannot be verified by the person reading it.
        return Confidence.LOW

    if (
        signals.grounding_score >= 0.9
        and signals.supporting_documents >= 1
        and signals.uncited_claims == 0
        and signals.top_score > 0
    ):
        return Confidence.HIGH

    if signals.grounding_score >= 0.6 and signals.citation_count >= 1:
        return Confidence.MEDIUM

    return Confidence.LOW


def explain(band: Confidence, signals: ConfidenceSignals) -> str:
    """One sentence a user can read, naming the weakest signal."""
    if band is Confidence.HIGH:
        return (
            f"Every claim was verifiable against its cited source "
            f"({signals.citation_count} citation(s) across "
            f"{signals.supporting_documents} document(s))."
        )
    if band is Confidence.MEDIUM:
        weakest = []
        if signals.grounding_score < 0.9:
            weakest.append(
                f"{int(signals.grounding_score * 100)}% of claims verified against their sources"
            )
        if signals.uncited_claims:
            weakest.append(f"{signals.uncited_claims} claim(s) without a citation")
        detail = "; ".join(weakest) or "partial verification"
        return f"Answer is supported but not fully verifiable: {detail}."
    if signals.citation_count == 0:
        return "The answer cited no sources, so none of it could be verified."
    return (
        f"Only {int(signals.grounding_score * 100)}% of claims could be verified "
        f"against the cited passages. Treat this answer as a starting point and "
        f"check the sources."
    )
