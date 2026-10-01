"""Context assembly, grounding verification, and confidence banding."""

from __future__ import annotations

import datetime as dt

from app.generation.citations import resolve
from app.generation.confidence import (
    Confidence,
    ConfidenceSignals,
    assess,
    compute_signals,
    explain,
)
from app.generation.context import build_context
from app.generation.grounding import lexical_support, verify
from app.generation.prompts import INSUFFICIENT_EVIDENCE, SYSTEM_PROMPT, build_user_prompt
from app.retrieval.types import Candidate
from tests.unit.test_citations import candidate


def sized_candidate(name: str, words: int) -> Candidate:
    return candidate(name, content=" ".join([f"{name}word"] * words))


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------
def test_blocks_are_numbered_from_one() -> None:
    bundle = build_context([candidate(f"d{i}") for i in range(3)])
    assert [b.number for b in bundle.blocks] == [1, 2, 3]


def test_context_respects_the_token_budget() -> None:
    bundle = build_context([sized_candidate(f"d{i}", 400) for i in range(10)], token_budget=500)
    assert len(bundle.blocks) < 10
    assert bundle.dropped_for_budget > 0


def test_budget_keeps_at_least_one_block() -> None:
    """A single oversized passage must still be shown - returning nothing
    would abstain on evidence we actually have."""
    bundle = build_context([sized_candidate("huge", 5000)], token_budget=10)
    assert len(bundle.blocks) == 1


def test_near_duplicate_passages_are_dropped() -> None:
    """Chunk overlap and restated policies produce near-identical passages;
    spending two context slots on the same text wastes a top-k position."""
    text = "The domestic meal cap is eighty five dollars per day for all employees"
    bundle = build_context([candidate("a", text), candidate("b", text)])
    assert len(bundle.blocks) == 1
    assert bundle.dropped_as_duplicate == 1


def test_passages_are_fenced_and_labelled() -> None:
    bundle = build_context([candidate("auth")])
    assert '<passage id="1">' in bundle.prompt_text
    assert "</passage>" in bundle.prompt_text
    assert "Source: auth.md" in bundle.prompt_text


def test_updated_date_is_included_when_known() -> None:
    c = candidate("policy")
    c.source_updated_at = dt.datetime(2026, 3, 1, tzinfo=dt.UTC)
    assert "Updated: 2026-03-01" in build_context([c]).prompt_text


def test_candidate_lookup_by_number() -> None:
    bundle = build_context([candidate("a"), candidate("b")])
    assert bundle.candidate_for(2).source_uri == "b.md"
    assert bundle.candidate_for(99) is None


def test_empty_candidates_gives_empty_bundle() -> None:
    assert build_context([]).is_empty


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------
def test_system_prompt_defines_the_abstention_sentinel() -> None:
    assert INSUFFICIENT_EVIDENCE in SYSTEM_PROMPT


def test_system_prompt_warns_about_injection() -> None:
    assert "DATA" in SYSTEM_PROMPT


def test_user_prompt_puts_the_question_last() -> None:
    prompt = build_user_prompt("What is the cap?", '<passage id="1">x</passage>')
    assert prompt.index("<passage") < prompt.index("What is the cap?")


# ---------------------------------------------------------------------------
# Grounding
# ---------------------------------------------------------------------------
def test_lexical_support_rewards_shared_content_words() -> None:
    passage = "The domestic meal cap is $85 per day, raised from $75 on 2026-01-01."
    assert lexical_support("The meal cap is $85 per day.", passage) > 0.8


def test_lexical_support_catches_a_changed_number() -> None:
    """The failure embeddings are worst at: $85 and $75 are near-identical in
    vector space and completely different in fact."""
    passage = "The domestic meal cap is $85 per day."
    right = lexical_support("The cap is $85 per day.", passage)
    wrong = lexical_support("The cap is $200 per day.", passage)
    assert right > wrong


def test_grounded_answer_scores_well() -> None:
    text = "The meal cap is eighty five dollars per day for domestic travel."
    bundle = build_context([candidate("expense", text)])
    report = verify(f"{text} [1]", bundle)
    assert report.passed
    assert report.score == 1.0


def test_unsupported_claim_is_flagged() -> None:
    bundle = build_context([candidate("expense", "The meal cap is eighty five dollars.")])
    report = verify(
        "Employees receive unlimited catered lunches at every regional office [1].", bundle
    )
    assert not report.passed
    assert report.unsupported_sentences


def test_answer_with_no_claim_sentences_is_vacuously_grounded() -> None:
    report = verify("Yes.", build_context([candidate("a")]))
    assert report.total_claims == 0
    assert report.passed


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------
def signals(**overrides: object) -> ConfidenceSignals:
    base = {
        "top_score": 0.05,
        "score_margin": 0.02,
        "supporting_documents": 2,
        "grounding_score": 1.0,
        "citation_count": 2,
        "uncited_claims": 0,
    }
    base.update(overrides)
    return ConfidenceSignals(**base)  # type: ignore[arg-type]


def test_fully_verified_answer_is_high() -> None:
    assert assess(signals()) is Confidence.HIGH


def test_zero_citations_is_always_low() -> None:
    """An answer citing nothing cannot be checked by the person reading it, no
    matter how good the retrieval scores were."""
    assert assess(signals(citation_count=0, grounding_score=1.0)) is Confidence.LOW


def test_partial_grounding_is_medium() -> None:
    assert assess(signals(grounding_score=0.7)) is Confidence.MEDIUM


def test_poor_grounding_is_low() -> None:
    assert assess(signals(grounding_score=0.2)) is Confidence.LOW


def test_uncited_claims_prevent_high() -> None:
    assert assess(signals(uncited_claims=2)) is not Confidence.HIGH


def test_signals_are_computed_from_the_pipeline() -> None:
    candidates = [candidate("a"), candidate("b"), candidate("c"), candidate("d")]
    for i, c in enumerate(candidates):
        c.rrf_score = 0.05 - i * 0.01
    bundle = build_context(candidates)
    citations = resolve("Claim [1]. Other [2].", bundle)
    report = verify("Claim [1]. Other [2].", bundle)

    computed = compute_signals(candidates, citations, report)
    assert computed.top_score == 0.05
    assert computed.score_margin > 0
    assert computed.supporting_documents == 2


def test_explanation_names_the_weakness() -> None:
    assert "cited no sources" in explain(Confidence.LOW, signals(citation_count=0))
    assert "verifiable" in explain(Confidence.HIGH, signals())


def test_no_percentage_is_ever_produced() -> None:
    """A percentage asserts calibration this system cannot demonstrate."""
    assert {c.value for c in Confidence} == {"high", "medium", "low"}
