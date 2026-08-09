"""The intermediate representation every parser produces.

Why an IR at all, instead of parser -> chunker directly?

Because chunking quality is the highest-leverage thing in a RAG system, and it
should be written once, tested once, and tuned once. If each parser did its own
chunking we would have four chunkers with four sets of bugs, and a change to
the packing policy would need four edits. Instead:

    PDF   ─┐
    DOCX  ─┼─► list[Block] ─► chunker ─► list[Chunk]
    MD    ─┤
    TXT   ─┘

A Block is a *semantic unit of a document* - one heading, one paragraph, one
fenced code block, one table. Blocks are never split by the parser; deciding
whether a block can be split is the chunker's job, and for code and tables the
answer is "only as a last resort".

The properties that matter downstream:

* `heading_path` - the H1 > H2 > H3 trail a block sits under. This is what
  gets prepended to the embedded text, and it is the single cheapest retrieval
  win available: a chunk reading "It uses OAuth 2.0 with a 3600s TTL" is
  unretrievable for the query "payment service authentication" until you glue
  "Payments Service > Authentication" onto the front of it.
* `atomic` - true for code and tables. Splitting a fenced code block in half
  produces two chunks, neither of which is valid code and neither of which
  answers anything.
* `line_start` / `line_end` - so a bad chunk can be traced back to source
  lines without guessing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class BlockType(StrEnum):
    """The block kinds we distinguish.

    Deliberately coarse. Finer distinctions (ordered vs unordered list, h1 vs
    h2 as separate types) would not change a single chunking decision.
    """

    HEADING = "heading"
    PARAGRAPH = "paragraph"
    CODE = "code"
    TABLE = "table"
    LIST = "list"
    QUOTE = "quote"
    RULE = "rule"


#: Block kinds the chunker must not split unless they exceed the hard maximum
#: on their own. A half table and a half code fence are both worthless.
ATOMIC_TYPES: frozenset[BlockType] = frozenset({BlockType.CODE, BlockType.TABLE})


@dataclass(slots=True)
class Block:
    """One semantic unit of a parsed document."""

    type: BlockType
    text: str

    #: Heading depth (1-6). Only meaningful when type is HEADING.
    level: int | None = None

    #: Fenced-code language tag, when the source declared one.
    lang: str | None = None

    #: 1-indexed source line span, for tracing a chunk back to the file.
    line_start: int = 0
    line_end: int = 0

    #: 1-indexed page number. Only PDFs populate this; it flows through to
    #: citations so a user can be sent to the right page.
    page: int | None = None

    #: ("Payments Service", "Authentication") - assigned by assign_heading_paths().
    heading_path: tuple[str, ...] = ()

    @property
    def is_atomic(self) -> bool:
        return self.type in ATOMIC_TYPES

    @property
    def is_heading(self) -> bool:
        return self.type is BlockType.HEADING

    @property
    def heading_trail(self) -> str:
        """'Payments Service > Authentication' - the display/prefix form."""
        return " > ".join(self.heading_path)


@dataclass(slots=True)
class ParsedDocument:
    """A document reduced to blocks, plus whatever the parser learned."""

    title: str
    blocks: list[Block]
    source_type: str
    source_uri: str
    #: Parser-derived extras (page count, detected encoding, ...). Manifest
    #: metadata is layered on top of this later, by the ingestion pipeline.
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        """Full document text, used for the content hash."""
        return "\n\n".join(b.text for b in self.blocks)


def assign_heading_paths(blocks: list[Block]) -> list[Block]:
    """Walk the block list and stamp each block with its heading trail.

    Mutates and returns the same list.

    Real documents skip heading levels (an H3 directly under an H1) and reset
    unpredictably. The rule here is the one a reader applies intuitively:
    a heading of level N replaces everything at depth >= N and appends itself.

        # Payments Service          -> path for following blocks: ("Payments Service",)
        ## Authentication           -> ("Payments Service", "Authentication")
        ### Service-to-service      -> ("Payments Service", "Authentication", "Service-to-service")
        ## Idempotency              -> ("Payments Service", "Idempotency")

    A heading block's own path *includes itself*, so a chunk that begins at a
    heading is labelled with that heading rather than with its parent.
    """
    # stack entries are (level, text)
    stack: list[tuple[int, str]] = []

    for block in blocks:
        if block.is_heading:
            level = block.level or 1
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, block.text.strip()))
            block.heading_path = tuple(text for _, text in stack)
        else:
            block.heading_path = tuple(text for _, text in stack)

    return blocks
