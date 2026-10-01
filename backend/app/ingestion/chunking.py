"""Structure-aware chunking.

A chunk is two things at once, and they want different sizes:

* the **retrieval unit** - what gets embedded and scored. Wants to be small
  and topically pure, so its embedding is not an average of four subjects.
* the **evidence unit** - what the model reads to answer. Wants to be large
  enough to contain a complete thought, or the model has to guess at the
  missing half.

Fixed-size splitting resolves that tension by ignoring it. Cutting every 512
characters severs sentences mid-clause, orphans code from the paragraph that
explains it, and - worst - strips headings. A chunk reading

    "It uses OAuth 2.0 with a token TTL of 3600 seconds."

has lost the word "payment" entirely. No amount of reranking recovers it,
because it was never retrievable for the query that needed it.

What this module does instead:

1. Pack whole blocks, never fragments of them, up to a target size.
2. Break at section boundaries, so a chunk covers one topic rather than the
   tail of one and the head of the next.
3. Never split code blocks or tables. Half a YAML example is not evidence.
4. Prefix every chunk with its heading path, so the chunk above becomes
   "Payments Service > Authentication\\n\\nIt uses OAuth 2.0 ...". That prefix
   is embedded AND indexed in the weight-A tsvector position, which is why it
   helps dense and keyword retrieval simultaneously.
5. Overlap only within a section, and only across prose - never duplicating a
   code block into two chunks.

Everything is measured, not asserted: `scripts/show_chunks.py` prints what this
produces for any file so the boundaries can be judged by eye before a single
embedding exists.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.ingestion.blocks import Block, BlockType, ParsedDocument
from app.ingestion.tokens import TokenCounter, get_token_counter

#: Blocks carrying no retrievable content. Dropping them stops a horizontal
#: rule from occupying a slot in the packing budget.
_SKIPPED_TYPES = frozenset({BlockType.RULE})

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\[\"'])")

#: Headroom left when splitting an oversized block, covering the code fences
#: and heading prefix added downstream of the split.
_SPLIT_MARGIN_TOKENS = 32


@dataclass(frozen=True, slots=True)
class ChunkingConfig:
    """Packing policy. All sizes in tokens."""

    #: Flush once a chunk reaches this size. The chunk usually lands slightly
    #: above it, because the block that crossed the line is kept whole.
    target_tokens: int = 450

    #: Hard ceiling. Only a single indivisible block may exceed this, and when
    #: one does it is split and flagged.
    max_tokens: int = 700

    #: Prose carried from the end of one chunk into the start of the next, so
    #: a fact spanning a boundary is retrievable from either side.
    overlap_tokens: int = 60

    #: Headings at this level or shallower force a new chunk. Level 2 means
    #: every `##` section starts fresh, which matches how documents are
    #: actually organised.
    break_on_heading_level: int = 2

    #: A trailing chunk smaller than this is merged backwards rather than left
    #: as a stub that will never win a retrieval.
    min_chunk_tokens: int = 40

    #: Prepend the heading trail to the embedded text.
    include_heading_prefix: bool = True

    @classmethod
    def from_settings(cls) -> ChunkingConfig:
        """Build from environment configuration.

        This is the default used by chunk_blocks. Without it the dataclass
        literals here and the CHUNK_* values in .env are two independent sets
        of numbers that can drift apart silently - and the corpus regression
        test would keep testing the old ones after a tuning change.
        """
        from app.core.config import get_settings

        settings = get_settings()
        return cls(
            target_tokens=settings.chunk_target_tokens,
            max_tokens=settings.chunk_max_tokens,
            overlap_tokens=settings.chunk_overlap_tokens,
        )


@dataclass(slots=True)
class Chunk:
    """One retrieval unit, ready to embed and store."""

    index: int
    #: Rendered block text, without the heading prefix.
    text: str
    #: What actually gets embedded and indexed: heading trail + text.
    embed_text: str
    heading_path: tuple[str, ...]
    token_count: int
    block_types: tuple[BlockType, ...]
    line_start: int
    line_end: int
    page_from: int | None = None
    page_to: int | None = None
    #: True when a single indivisible block had to be split to fit.
    is_split_block: bool = False
    #: True when this chunk begins with prose duplicated from the previous one.
    has_overlap: bool = False

    @property
    def heading_trail(self) -> str:
        return " > ".join(self.heading_path)


@dataclass(slots=True)
class ChunkingStats:
    """Aggregate numbers for the CLI and for regression checks."""

    document_count: int = 0
    block_count: int = 0
    chunk_count: int = 0
    token_counts: list[int] = field(default_factory=list)
    oversized: int = 0
    split_blocks: int = 0

    def add(self, chunks: list[Chunk], blocks: int, max_tokens: int) -> None:
        self.document_count += 1
        self.block_count += blocks
        self.chunk_count += len(chunks)
        self.token_counts.extend(c.token_count for c in chunks)
        self.oversized += sum(1 for c in chunks if c.token_count > max_tokens)
        self.split_blocks += sum(1 for c in chunks if c.is_split_block)

    @property
    def mean_tokens(self) -> float:
        return sum(self.token_counts) / len(self.token_counts) if self.token_counts else 0.0

    @property
    def median_tokens(self) -> float:
        if not self.token_counts:
            return 0.0
        ordered = sorted(self.token_counts)
        mid = len(ordered) // 2
        if len(ordered) % 2:
            return float(ordered[mid])
        return (ordered[mid - 1] + ordered[mid]) / 2

    @property
    def max_tokens_seen(self) -> int:
        return max(self.token_counts, default=0)

    @property
    def min_tokens_seen(self) -> int:
        return min(self.token_counts, default=0)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def render_block(block: Block) -> str:
    """Turn a block back into text for embedding and for the LLM prompt.

    Code is re-fenced and headings keep their hashes. Both are signals the
    model reads: an unfenced code sample invites the model to treat identifiers
    as prose, and a heading without its marker reads as a sentence fragment.
    """
    if block.type is BlockType.CODE:
        lang = block.lang or ""
        return f"```{lang}\n{block.text}\n```"
    if block.type is BlockType.HEADING:
        return f"{'#' * (block.level or 1)} {block.text}"
    return block.text


def render_blocks(blocks: list[Block]) -> str:
    return "\n\n".join(render_block(b) for b in blocks).strip()


def build_embed_text(text: str, heading_path: tuple[str, ...], *, include_prefix: bool) -> str:
    """Prepend the heading trail to the chunk body.

    When the chunk already opens with its own leaf heading, only the ancestors
    are prefixed - repeating the leaf verbatim adds tokens without adding
    signal.
    """
    if not include_prefix or not heading_path:
        return text

    trail = heading_path
    first_line = text.lstrip().split("\n", 1)[0].lstrip("#").strip()
    if first_line and first_line == heading_path[-1]:
        trail = heading_path[:-1]

    if not trail:
        return text
    return f"{' > '.join(trail)}\n\n{text}"


# ---------------------------------------------------------------------------
# Splitting oversized blocks
# ---------------------------------------------------------------------------
def _hard_split(piece: str, limit: int, counter: TokenCounter, *, is_code: bool) -> list[str]:
    """Last-resort whitespace split for a piece that is still too large.

    Needed because the preferred boundaries are not guaranteed to exist: a
    paragraph with no sentence-ending punctuation, or a minified line in a code
    block, offers nothing to split on. Without this fallback such a block
    silently sails past the ceiling and blows the context budget downstream.
    """
    words = piece.split()
    if not words:
        return [piece]

    out: list[str] = []
    buffer: list[str] = []
    buffer_tokens = 0
    for word in words:
        word_tokens = counter.count(word, is_code=is_code)
        if buffer and buffer_tokens + word_tokens > limit:
            out.append(" ".join(buffer))
            buffer, buffer_tokens = [], 0
        buffer.append(word)
        buffer_tokens += word_tokens
    if buffer:
        out.append(" ".join(buffer))
    return out


def _split_oversized(
    block: Block, config: ChunkingConfig, counter: TokenCounter
) -> list[list[Block]]:
    """Break one too-large block into groups that each fit under max_tokens.

    Code and tables split on line boundaries - the only place a split does not
    destroy meaning. Prose splits on sentence boundaries. Anything still over
    the ceiling after that is split on whitespace, because the ceiling is a
    guarantee and preferred boundaries are only a preference.
    """
    is_code = block.type is BlockType.CODE
    is_table = block.type is BlockType.TABLE
    #: A split table fragment starting at row 200 is a wall of unlabelled
    #: pipes. Repeating the header and separator on every fragment keeps each
    #: one readable as evidence on its own.
    table_header: list[str] = []
    if is_code or is_table:
        pieces = block.text.split("\n")
        if is_table and len(pieces) > 2:
            table_header = pieces[:2]
        joiner = "\n"
    else:
        pieces = _SENTENCE_BOUNDARY.split(block.text)
        joiner = " "

    # Leave room for the code fences and heading prefix that render_block and
    # build_embed_text add after this point, so fragments sized right at the
    # ceiling do not cross it once decorated.
    limit = max(1, config.max_tokens - _SPLIT_MARGIN_TOKENS)

    bounded: list[str] = []
    for piece in pieces:
        if counter.count(piece, is_code=is_code) <= limit:
            bounded.append(piece)
        else:
            bounded.extend(_hard_split(piece, limit, counter, is_code=is_code))

    groups: list[list[Block]] = []
    buffer: list[str] = []
    buffer_tokens = 0

    def emit() -> None:
        rows = buffer
        # Re-attach the header to every fragment after the first.
        if table_header and groups and rows[: len(table_header)] != table_header:
            rows = table_header + rows
        groups.append([_fragment(block, joiner.join(rows))])

    for piece in bounded:
        piece_tokens = counter.count(piece, is_code=is_code)
        if buffer and buffer_tokens + piece_tokens > limit:
            emit()
            buffer, buffer_tokens = [], 0
        buffer.append(piece)
        buffer_tokens += piece_tokens

    if buffer:
        emit()

    return groups or [[block]]


def _prefix_cost(
    heading_path: tuple[str, ...], config: ChunkingConfig, counter: TokenCounter
) -> int:
    """Token cost of the heading trail that will be prepended to this chunk.

    The packing loop has to know this. It used to size chunks from block text
    alone while _make_chunk stamped `body + prefix` onto the result, so every
    flush decision was made against a number smaller than the one later
    reported - and a chunk could be recorded as over the ceiling that the
    packer believed was under it.
    """
    if not config.include_heading_prefix or not heading_path:
        return 0
    # +2 approximates the blank line between the trail and the body.
    return counter.count(" > ".join(heading_path)) + 2


def _fragment(source: Block, text: str) -> Block:
    return Block(
        type=source.type,
        text=text,
        level=source.level,
        lang=source.lang,
        line_start=source.line_start,
        line_end=source.line_end,
        page=source.page,
        heading_path=source.heading_path,
    )


# ---------------------------------------------------------------------------
# The chunker
# ---------------------------------------------------------------------------
def chunk_blocks(
    blocks: list[Block],
    config: ChunkingConfig | None = None,
    counter: TokenCounter | None = None,
) -> list[Chunk]:
    """Pack blocks into chunks. Pure function - no I/O, fully deterministic."""
    config = config or ChunkingConfig.from_settings()
    counter = counter or get_token_counter()

    content = [b for b in blocks if b.type not in _SKIPPED_TYPES and b.text.strip()]
    if not content:
        return []

    chunks: list[Chunk] = []
    current: list[Block] = []
    current_tokens = 0
    carried_overlap = False
    #: How many leading blocks of `current` were duplicated from the previous
    #: chunk. Needed so a buffer made of nothing but carried text is not
    #: emitted as a chunk with no new content in it.
    carried_count = 0

    def block_tokens(block: Block) -> int:
        return counter.count(render_block(block), is_code=block.type is BlockType.CODE)

    def ceiling_for(block: Block) -> int:
        """Ceiling in body tokens, leaving room for the heading prefix."""
        return max(1, config.max_tokens - _prefix_cost(block.heading_path, config, counter))

    def flush() -> bool:
        """Emit the buffer as a chunk. Returns False if it declined to.

        Two buffers are held back rather than emitted: one of nothing but
        headings (a label, not evidence - it joins the section it introduces),
        and one of nothing but carried overlap (every token already indexed on
        the previous chunk, so emitting it spends a top-k slot on a duplicate).
        """
        nonlocal current, current_tokens, carried_overlap, carried_count
        if not current or all(b.is_heading for b in current):
            return False
        if carried_count and carried_count == len(current):
            current, current_tokens, carried_overlap, carried_count = [], 0, False, 0
            return False
        chunks.append(
            _make_chunk(
                len(chunks), current, config, counter, False, carried_overlap, carried_count
            )
        )
        current, current_tokens, carried_overlap, carried_count = [], 0, False, 0
        return True

    def start_next_with_overlap(previous: list[Block], incoming_tokens: int = 0) -> None:
        """Seed the next chunk with trailing prose from the one just flushed.

        `incoming_tokens` is the size of the block about to be appended. The
        overlap budget is capped so that carrying context can never by itself
        push the next chunk over the ceiling - context is a nice-to-have, the
        ceiling is a guarantee.
        """
        nonlocal current, current_tokens, carried_overlap, carried_count
        current, current_tokens, carried_overlap, carried_count = [], 0, False, 0
        if config.overlap_tokens <= 0 or not previous:
            return

        budget = config.overlap_tokens
        if incoming_tokens:
            headroom = ceiling_for(previous[-1]) - incoming_tokens
            budget = min(budget, headroom)
        if budget <= 0:
            return

        tail: list[Block] = []
        total = 0
        for block in reversed(previous):
            # Never duplicate code or tables, and never carry a heading - the
            # next chunk gets its heading path from heading_path anyway.
            if block.is_atomic or block.is_heading:
                break
            tokens = block_tokens(block)
            if total + tokens > budget:
                break
            tail.insert(0, block)
            total += tokens
        if tail:
            current = list(tail)
            current_tokens = total
            carried_overlap = True
            carried_count = len(tail)

    for block in content:
        # --- section boundary --------------------------------------------
        # No overlap is carried across a section break: the whole point of the
        # break is that the next chunk is about something else.
        if block.is_heading and (block.level or 1) <= config.break_on_heading_level and current:
            flush()

        tokens = block_tokens(block)
        ceiling = ceiling_for(block)

        # --- a single block larger than the ceiling -----------------------
        if tokens > ceiling:
            flush()
            # Anything left in `current` here is a pending heading, which rides
            # along with the first fragment so the fragment keeps its label.
            for group in _split_oversized(block, config, counter):
                chunks.append(
                    _make_chunk(
                        len(chunks), current + group, config, counter, True, carried_overlap
                    )
                )
                current, current_tokens, carried_overlap, carried_count = [], 0, False, 0
            continue

        # --- would overflow the ceiling ----------------------------------
        if current and current_tokens + tokens > ceiling:
            previous = list(current)
            if flush():
                start_next_with_overlap(previous, incoming_tokens=tokens)

        current.append(block)
        current_tokens += tokens

        # --- reached the target ------------------------------------------
        if current_tokens >= config.target_tokens:
            previous = list(current)
            if flush():
                start_next_with_overlap(previous)

    # Terminal flush. If the buffer was declined - a document that ends in
    # headings, or one that is nothing but headings - emit it anyway rather
    # than dropping it on the floor. Silently losing content is the one
    # failure mode an ingestion pipeline must never have.
    if not flush() and current:
        chunks.append(
            _make_chunk(
                len(chunks), current, config, counter, False, carried_overlap, carried_count
            )
        )

    return _merge_stub_tail(chunks, config, counter)


def _make_chunk(
    index: int,
    blocks: list[Block],
    config: ChunkingConfig,
    counter: TokenCounter,
    split: bool,
    has_overlap: bool,
    carried_count: int = 0,
) -> Chunk:
    text = render_blocks(blocks)

    # The heading path of a chunk is the path of its first *own* content block.
    # Two things are being avoided here:
    #   * taking blocks[0] would label a chunk opening "# Doc / ## Auth / body"
    #     as "Doc" and lose the section entirely;
    #   * taking the first content block would, on a chunk seeded with overlap,
    #     label it with the PREVIOUS section - producing a chunk whose heading
    #     trail contradicts the body two lines below it.
    own = blocks[carried_count:] or blocks
    anchor = next((b for b in own if not b.is_heading), own[-1])
    heading_path = anchor.heading_path

    embed_text = build_embed_text(text, heading_path, include_prefix=config.include_heading_prefix)

    # Size the chunk as the sum of its blocks, using each block's own ratio.
    # Counting the whole chunk in one call would apply a single ratio to mixed
    # content - a 500-char paragraph next to a code block would be measured at
    # the code ratio and appear ~40% larger than the packing loop believed.
    body_tokens = sum(
        counter.count(render_block(b), is_code=b.type is BlockType.CODE) for b in blocks
    )
    prefix_tokens = counter.count(embed_text[: max(0, len(embed_text) - len(text))])

    pages = [b.page for b in blocks if b.page is not None]
    line_starts = [b.line_start for b in blocks if b.line_start]
    line_ends = [b.line_end for b in blocks if b.line_end]

    return Chunk(
        index=index,
        text=text,
        embed_text=embed_text,
        heading_path=heading_path,
        token_count=body_tokens + prefix_tokens,
        block_types=tuple(b.type for b in blocks),
        line_start=min(line_starts, default=0),
        line_end=max(line_ends, default=0),
        page_from=min(pages) if pages else None,
        page_to=max(pages) if pages else None,
        is_split_block=split,
        has_overlap=has_overlap,
    )


def _merge_stub_tail(
    chunks: list[Chunk], config: ChunkingConfig, counter: TokenCounter
) -> list[Chunk]:
    """Fold a too-small final chunk back into its predecessor.

    A 12-token trailing chunk ("## Revision History") will never win a
    retrieval on its own and only dilutes the index.
    """
    if len(chunks) < 2:
        return chunks

    last, previous = chunks[-1], chunks[-2]
    if last.token_count >= config.min_chunk_tokens:
        return chunks
    if last.heading_path[:1] != previous.heading_path[:1]:
        return chunks
    if previous.token_count + last.token_count > config.max_tokens:
        return chunks

    text = f"{previous.text}\n\n{last.text}"
    embed_text = build_embed_text(
        text, previous.heading_path, include_prefix=config.include_heading_prefix
    )
    merged = Chunk(
        index=previous.index,
        text=text,
        embed_text=embed_text,
        heading_path=previous.heading_path,
        # Consistent with _make_chunk: sum the parts rather than re-measuring
        # mixed content with a single ratio.
        token_count=previous.token_count + last.token_count,
        block_types=previous.block_types + last.block_types,
        line_start=previous.line_start,
        line_end=max(previous.line_end, last.line_end),
        page_from=previous.page_from,
        page_to=last.page_to or previous.page_to,
        is_split_block=previous.is_split_block or last.is_split_block,
        has_overlap=previous.has_overlap,
    )
    return [*chunks[:-2], merged]


def chunk_document(
    document: ParsedDocument,
    config: ChunkingConfig | None = None,
    counter: TokenCounter | None = None,
) -> list[Chunk]:
    """Chunk a parsed document."""
    return chunk_blocks(document.blocks, config, counter)
