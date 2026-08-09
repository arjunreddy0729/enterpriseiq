"""Citation resolution and validation.

The property being defended: the model cannot produce a source that did not
exist. It emits numbers; the server owns the mapping; anything outside the
mapping is dropped rather than rendered as if it were real.
"""

from __future__ import annotations

import uuid

from app.generation.citations import (
    count_uncited_sentences,
    extract_numbers,
    resolve,
    split_sentences,
)
from app.generation.context import ContextBlock, ContextBundle
from app.retrieval.types import Candidate


def candidate(name: str, content: str | None = None) -> Candidate:
    # Content must be genuinely distinct per candidate: the context builder
    # collapses near-duplicates, so filler that differs only in one short
    # token still gets deduplicated (correctly) and the fixture silently
    # produces one block instead of the several the test expects.
    content = content or " ".join(f"{name}term{i}" for i in range(12))
    return Candidate(
        chunk_id=uuid.uuid5(uuid.NAMESPACE_DNS, name),
        document_id=uuid.uuid5(uuid.NAMESPACE_DNS, f"doc-{name}"),
        content=content,
        embed_text=content,
        section_path=f"{name} > Section",
        document_title=name,
        source_uri=f"{name}.md",
        department="engineering",
        doc_type="policy",
        classification="internal",
        chunk_index=0,
    )


def bundle_of(n: int) -> ContextBundle:
    blocks = [ContextBlock(number=i, candidate=candidate(f"doc{i}")) for i in range(1, n + 1)]
    return ContextBundle(blocks=blocks)


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------
def test_extract_simple_and_stacked_markers() -> None:
    assert extract_numbers("A claim [1]. Another [2][3].") == [1, 2, 3]


def test_non_numeric_brackets_are_not_citations() -> None:
    assert extract_numbers("See [appendix] and [1.2] and [1]") == [1]


# ---------------------------------------------------------------------------
# The core guarantee
# ---------------------------------------------------------------------------
def test_fabricated_citation_number_is_dropped() -> None:
    """The model cited [7] with only 3 passages supplied. It must not appear
    as a source, and the marker must not survive in the text looking real."""
    result = resolve("Real claim [1]. Invented claim [7].", bundle_of(3))
    assert result.invalid_numbers == [7]
    assert "[7]" not in result.answer
    assert [c.number for c in result.citations] == [1]


def test_only_cited_passages_become_sources() -> None:
    """Six passages were retrieved; the answer used one. The sources list must
    show what was used, not what was available."""
    result = resolve("A claim [2].", bundle_of(6))
    assert len(result.citations) == 1
    assert result.citations[0].source_uri == "doc2.md"


def test_citations_are_renumbered_contiguously() -> None:
    """A reader must never see [1] then [4] and wonder what is missing."""
    result = resolve("First [3]. Second [5].", bundle_of(6))
    assert [c.number for c in result.citations] == [1, 2]
    assert "[1]" in result.answer and "[2]" in result.answer
    assert "[3]" not in result.answer and "[5]" not in result.answer


def test_renumbering_follows_order_of_appearance() -> None:
    result = resolve("Later source first [4]. Then [2].", bundle_of(4))
    by_number = {c.number: c.source_uri for c in result.citations}
    assert by_number[1] == "doc4.md"
    assert by_number[2] == "doc2.md"


def test_repeated_citation_resolves_once() -> None:
    result = resolve("One [1]. Two [1]. Three [1].", bundle_of(2))
    assert len(result.citations) == 1
    assert result.answer.count("[1]") == 3


def test_answer_with_no_citations() -> None:
    result = resolve("A bare assertion with no source at all.", bundle_of(3))
    assert result.citations == []
    assert result.citation_count == 0


def test_citation_carries_real_document_metadata() -> None:
    """Every field is looked up server-side - none of it is model output."""
    citation = resolve("Claim [1].", bundle_of(1)).citations[0]
    assert citation.source_uri == "doc1.md"
    assert citation.document_title == "doc1"
    assert citation.section_path == "doc1 > Section"
    assert isinstance(citation.chunk_id, uuid.UUID)


def test_dropping_a_marker_does_not_leave_a_dangling_space() -> None:
    result = resolve("A claim [9] .", bundle_of(2))
    assert "  " not in result.answer
    assert " ." not in result.answer


# ---------------------------------------------------------------------------
# Uncited claim detection
# ---------------------------------------------------------------------------
def test_sentences_split() -> None:
    assert len(split_sentences("One. Two! Three?")) == 3


def test_uncited_claim_sentences_are_counted() -> None:
    text = "This is a substantive claim with no citation attached to it. Cited one [1]."
    assert count_uncited_sentences(text) == 1


def test_short_connective_sentences_are_not_treated_as_claims() -> None:
    """Demanding a citation for 'Here is what I found.' would only teach the
    model to attach meaningless ones."""
    assert count_uncited_sentences("Here it is. Sure.") == 0
