"""Citation resolution and validation.

The model never names a source. It is shown numbered passages and asked to
write [1], [2]; the mapping from number to chunk lives on the server, and this
module resolves the numbers back into real documents.

That inversion is the whole point. If you ask a model to produce citations as
text - "according to compensation-policy.md" - you have asked it to generate a
fact, and it will generate one whether or not it is true. A number that is
looked up in a server-side table cannot be fabricated: a number outside the
table is dropped here, and the answer is reported as having one fewer citation
rather than one more source than existed.

What this module enforces:

* every [n] in the answer maps to a passage that was actually supplied
* invalid markers are stripped from the text, not silently left to look real
* only cited passages are returned as sources, so the sources list is what was
  used rather than what was retrieved
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from app.core.logging import get_logger
from app.generation.context import ContextBundle
from app.retrieval.types import Candidate

logger = get_logger(__name__)

#: Matches [1] and the [2][3] form. Deliberately not matching [a] or [1.2] -
#: anything that is not a bare integer is not a citation this system issued.
_CITATION = re.compile(r"\[(\d{1,3})\]")


@dataclass(slots=True)
class Citation:
    """A resolved source, renumbered to be contiguous in the final answer."""

    number: int
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    section_path: str | None
    source_uri: str
    updated_at: str | None
    snippet: str

    @classmethod
    def from_candidate(cls, number: int, candidate: Candidate) -> Citation:
        return cls(
            number=number,
            chunk_id=candidate.chunk_id,
            document_id=candidate.document_id,
            document_title=candidate.document_title,
            section_path=candidate.section_path,
            source_uri=candidate.source_uri,
            updated_at=(
                candidate.source_updated_at.date().isoformat()
                if candidate.source_updated_at
                else None
            ),
            snippet=candidate.content.strip(),
        )


@dataclass(slots=True)
class CitationResult:
    answer: str
    citations: list[Citation]
    invalid_numbers: list[int]
    uncited_sentences: int

    @property
    def citation_count(self) -> int:
        return len(self.citations)


def extract_numbers(text: str) -> list[int]:
    """Every [n] in order of appearance, duplicates included."""
    return [int(match.group(1)) for match in _CITATION.finditer(text)]


def resolve(answer: str, bundle: ContextBundle) -> CitationResult:
    """Validate the answer's citations and resolve them to real sources.

    Returns the answer with invalid markers removed and citations renumbered
    contiguously from 1, so a reader never sees a gap like [1] [4] and wonders
    what happened to the two in between.
    """
    valid = bundle.valid_numbers
    cited = extract_numbers(answer)

    invalid = sorted({n for n in cited if n not in valid})
    if invalid:
        # Not an error: the model referenced a passage that does not exist, we
        # noticed, and the claim loses its citation rather than gaining a fake
        # source. Logged because a rising rate here means the prompt is drifting.
        logger.warning("invalid_citation_numbers", invalid=invalid, valid=sorted(valid))

    # Renumber in order of first appearance among the valid ones.
    order: list[int] = []
    for number in cited:
        if number in valid and number not in order:
            order.append(number)

    renumbering = {original: index for index, original in enumerate(order, start=1)}

    def replace(match: re.Match[str]) -> str:
        number = int(match.group(1))
        if number not in renumbering:
            return ""  # drop invalid markers entirely
        return f"[{renumbering[number]}]"

    cleaned = _CITATION.sub(replace, answer)
    cleaned = re.sub(r" +([.,;:])", r"\1", cleaned)  # tidy space left by a drop
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()

    citations = [
        Citation.from_candidate(new_number, bundle.candidate_for(original))  # type: ignore[arg-type]
        for original, new_number in renumbering.items()
    ]
    citations.sort(key=lambda c: c.number)

    return CitationResult(
        answer=cleaned,
        citations=citations,
        invalid_numbers=invalid,
        uncited_sentences=count_uncited_sentences(cleaned),
    )


_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE.split(text.strip()) if s.strip()]


def count_uncited_sentences(answer: str) -> int:
    """Sentences making a claim with no citation attached.

    Short connective sentences are ignored - "Here is what I found." is not a
    factual claim and demanding a citation for it would only teach the model to
    attach meaningless ones.
    """
    return sum(
        1
        for sentence in split_sentences(answer)
        if len(sentence.split()) >= 6 and not _CITATION.search(sentence)
    )
