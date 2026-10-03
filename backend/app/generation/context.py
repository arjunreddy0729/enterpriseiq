"""Context assembly.

The job is not "fit as much as possible into the window". It is "give the
model the smallest set of passages that actually answers the question", for
three reasons that all point the same way:

* Every irrelevant passage is a chance for the model to answer from the wrong
  one. Recall problems become precision problems once they reach the prompt.
* Tokens cost money and latency, on every single request.
* Attention is finite. A relevant passage buried among nine irrelevant ones is
  measurably less likely to be used than the same passage on its own.

The other thing this module owns is **citation identity**. Each block is
assigned a number here, on the server, and the mapping from number to chunk is
kept. The model is only ever asked to reference those numbers - it never names
a document, and it cannot invent a source that survives validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.config import get_settings
from app.ingestion.tokens import TokenCounter, get_token_counter
from app.retrieval.types import Candidate

#: Passages whose content overlaps a already-included passage by more than
#: this fraction are dropped. Near-duplicates arise from chunk overlap and
#: from the same policy being restated in two documents.
_DUPLICATE_THRESHOLD = 0.85


@dataclass(slots=True)
class ContextBlock:
    """One numbered passage in the prompt."""

    number: int
    candidate: Candidate


@dataclass(slots=True)
class ContextBundle:
    """The assembled context plus the citation mapping it defines."""

    blocks: list[ContextBlock] = field(default_factory=list)
    prompt_text: str = ""
    token_count: int = 0
    dropped_for_budget: int = 0
    dropped_as_duplicate: int = 0

    @property
    def is_empty(self) -> bool:
        return not self.blocks

    def candidate_for(self, number: int) -> Candidate | None:
        for block in self.blocks:
            if block.number == number:
                return block.candidate
        return None

    @property
    def valid_numbers(self) -> set[int]:
        return {block.number for block in self.blocks}

    def to_debug(self) -> dict[str, object]:
        return {
            "blocks": len(self.blocks),
            "context_tokens": self.token_count,
            "dropped_for_budget": self.dropped_for_budget,
            "dropped_as_duplicate": self.dropped_as_duplicate,
        }


def _token_set(text: str) -> set[str]:
    return {w for w in text.lower().split() if len(w) > 3}


def _overlap(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def build_context(
    candidates: list[Candidate],
    token_budget: int | None = None,
    counter: TokenCounter | None = None,
) -> ContextBundle:
    """Assemble numbered context blocks within a token budget."""
    settings = get_settings()
    budget = token_budget or settings.context_token_budget
    counter = counter or get_token_counter()

    bundle = ContextBundle()
    seen: list[set[str]] = []
    used_tokens = 0

    for candidate in candidates:
        tokens = _token_set(candidate.content)
        if any(_overlap(tokens, previous) >= _DUPLICATE_THRESHOLD for previous in seen):
            bundle.dropped_as_duplicate += 1
            continue

        number = len(bundle.blocks) + 1
        rendered = _render_block(number, candidate)
        cost = counter.count(rendered)

        if used_tokens + cost > budget and bundle.blocks:
            # Budget exhausted. Stop rather than skip-and-continue: candidates
            # are in relevance order, so anything after this is weaker still.
            bundle.dropped_for_budget = len(candidates) - len(bundle.blocks)
            break

        bundle.blocks.append(ContextBlock(number=number, candidate=candidate))
        seen.append(tokens)
        used_tokens += cost

    bundle.prompt_text = "\n\n".join(
        _render_block(block.number, block.candidate) for block in bundle.blocks
    )
    bundle.token_count = used_tokens
    return bundle


def _render_block(number: int, candidate: Candidate) -> str:
    """Render one passage for the prompt.

    The metadata header is not decoration. `Updated` lets the model prefer a
    newer statement when two passages disagree, and the source path is what
    makes a citation checkable by the person reading the answer.

    Passage text is fenced in an explicit delimiter and the system prompt
    states that everything inside is data. Retrieved documents are untrusted
    input - a document containing "ignore previous instructions" is a
    prompt-injection vector, and the fence plus the instruction is the cheap
    part of defending against it.
    """
    parts = [f'<passage id="{number}">']
    parts.append(f"Title: {candidate.document_title}")
    if candidate.section_path:
        parts.append(f"Section: {candidate.section_path}")
    parts.append(f"Source: {candidate.source_uri}")
    if candidate.source_updated_at:
        parts.append(f"Updated: {candidate.source_updated_at.date().isoformat()}")
    parts.append("")
    parts.append(candidate.content.strip())
    parts.append("</passage>")
    return "\n".join(parts)
