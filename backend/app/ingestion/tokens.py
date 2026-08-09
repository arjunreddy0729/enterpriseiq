"""Token counting for chunk sizing.

Chunk budgets are expressed in tokens because that is what both the embedding
model and the LLM context window are denominated in. But counting tokens
*exactly* means loading the BGE tokenizer, which means pulling in
`transformers` and downloading model files - a heavy dependency for a decision
that only needs to be roughly right.

So there are two implementations behind one Protocol:

* HeuristicTokenCounter - always available, no dependencies, no downloads.
  Character-ratio based, with a separate ratio for code (which tokenizes
  denser than prose because of punctuation and identifiers).
* HuggingFaceTokenCounter - exact, used when `transformers` is installed and
  the caller explicitly asks for it.

The heuristic is used by default and is honest about being an estimate. Being
20 tokens off on a 450-token chunk changes nothing; the packing decisions are
identical. What would matter is being *systematically* wrong in a way that
lets chunks blow past the LLM context budget, which is why the context builder
later re-counts with the exact counter before assembling a prompt.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Protocol, runtime_checkable

# Empirical character-per-token ratios for BERT-family WordPiece tokenizers
# (BGE is BERT-based) on English text. Prose averages ~3.8 chars/token; code
# is denser at ~2.9 because identifiers, brackets and punctuation each split.
_CHARS_PER_TOKEN_PROSE = 3.8
_CHARS_PER_TOKEN_CODE = 2.9

# Whitespace runs collapse to a single token at most, so normalising first
# stops heavily-indented code from inflating the estimate.
_WHITESPACE_RUN = re.compile(r"\s+")


@runtime_checkable
class TokenCounter(Protocol):
    """Anything that can size a string in tokens."""

    def count(self, text: str, *, is_code: bool = False) -> int: ...

    @property
    def name(self) -> str: ...

    @property
    def exact(self) -> bool: ...


class HeuristicTokenCounter:
    """Dependency-free character-ratio estimator."""

    @property
    def name(self) -> str:
        return "heuristic"

    @property
    def exact(self) -> bool:
        return False

    def count(self, text: str, *, is_code: bool = False) -> int:
        if not text:
            return 0
        normalised = _WHITESPACE_RUN.sub(" ", text).strip()
        if not normalised:
            return 0
        ratio = _CHARS_PER_TOKEN_CODE if is_code else _CHARS_PER_TOKEN_PROSE
        return max(1, round(len(normalised) / ratio))


class HuggingFaceTokenCounter:
    """Exact counts from the real tokenizer.

    Requires `transformers` (the `ml` extra) and downloads the tokenizer files
    on first use. Constructed only on explicit request - never as a silent
    default, because a surprise network call inside a chunking loop is a bad
    failure mode.
    """

    def __init__(self, model_name: str) -> None:
        try:
            from transformers import AutoTokenizer
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise RuntimeError(
                "Exact token counting needs the 'ml' extra: pip install '.[ml]'"
            ) from exc

        self._model_name = model_name
        self._tokenizer = AutoTokenizer.from_pretrained(model_name)

    @property
    def name(self) -> str:
        return self._model_name

    @property
    def exact(self) -> bool:
        return True

    def count(self, text: str, *, is_code: bool = False) -> int:
        if not text:
            return 0
        # add_special_tokens=False: we are measuring content, and the [CLS]/[SEP]
        # pair is added once per encode call, not once per chunk fragment.
        return len(self._tokenizer.encode(text, add_special_tokens=False))


@lru_cache(maxsize=4)
def get_token_counter(model_name: str | None = None) -> TokenCounter:
    """Return a counter. Pass a model name to get exact counts.

    Cached because constructing the HF tokenizer is expensive and the chunker
    calls this per document.
    """
    if model_name:
        return HuggingFaceTokenCounter(model_name)
    return HeuristicTokenCounter()
