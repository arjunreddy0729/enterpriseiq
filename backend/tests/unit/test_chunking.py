"""Chunker invariants.

These are the properties that must hold for every chunk the system ever
produces, because each one maps to a retrieval failure if violated:

* over the token ceiling  -> blows the context budget, or silently truncates
* a split code block      -> neither half is valid evidence
* a lost heading path     -> the chunk becomes unretrievable for its own topic
* overlap across sections -> a chunk about A carries text about B, and the
                             embedding is an average of the two
"""

from __future__ import annotations

import pytest

from app.ingestion.blocks import Block, BlockType, assign_heading_paths
from app.ingestion.chunking import (
    ChunkingConfig,
    build_embed_text,
    chunk_blocks,
    render_block,
)
from app.ingestion.tokens import HeuristicTokenCounter

counter = HeuristicTokenCounter()


def heading(text: str, level: int = 2) -> Block:
    return Block(type=BlockType.HEADING, text=text, level=level)


def para(text: str) -> Block:
    return Block(type=BlockType.PARAGRAPH, text=text)


def code(text: str, lang: str = "python") -> Block:
    return Block(type=BlockType.CODE, text=text, lang=lang)


def words(n: int) -> str:
    """Roughly n tokens of filler prose."""
    return " ".join(["alpha"] * n)


# ---------------------------------------------------------------------------
# Size invariants
# ---------------------------------------------------------------------------
def test_no_chunk_exceeds_max_unless_it_is_a_split_block() -> None:
    blocks = assign_heading_paths([heading("Doc", 1)] + [para(words(60)) for _ in range(30)])
    config = ChunkingConfig(target_tokens=200, max_tokens=300, overlap_tokens=0)
    chunks = chunk_blocks(blocks, config, counter)

    assert chunks
    for chunk in chunks:
        assert chunk.token_count <= config.max_tokens, (
            f"chunk {chunk.index} is {chunk.token_count} tokens"
        )


def test_a_single_oversized_block_is_split_and_flagged() -> None:
    blocks = assign_heading_paths([heading("Doc", 1), para(words(2000))])
    config = ChunkingConfig(target_tokens=200, max_tokens=300)
    chunks = chunk_blocks(blocks, config, counter)

    assert len(chunks) > 1
    assert all(c.is_split_block for c in chunks)


def test_empty_input_produces_no_chunks() -> None:
    assert chunk_blocks([], ChunkingConfig(), counter) == []
    assert chunk_blocks([Block(type=BlockType.RULE, text="---")], None, counter) == []


def test_no_chunk_is_empty() -> None:
    blocks = assign_heading_paths([heading("Doc", 1), para("short body")])
    for chunk in chunk_blocks(blocks, None, counter):
        assert chunk.text.strip()
        assert chunk.token_count > 0


# ---------------------------------------------------------------------------
# Atomicity
# ---------------------------------------------------------------------------
def test_code_block_is_never_split_when_it_fits() -> None:
    body = "\n".join(f"line_{i} = {i}" for i in range(20))
    blocks = assign_heading_paths([heading("Doc", 1), para(words(100)), code(body)])
    chunks = chunk_blocks(blocks, ChunkingConfig(target_tokens=80, max_tokens=600), counter)

    fenced = [c for c in chunks if "```" in c.text]
    assert fenced, "expected the code block to survive somewhere"
    for chunk in chunks:
        # Balanced fences: an odd count means a fence was cut in half.
        assert chunk.text.count("```") % 2 == 0


def test_table_is_never_split_when_it_fits() -> None:
    table = Block(
        type=BlockType.TABLE,
        text="\n".join(f"| r{i} | v{i} |" for i in range(15)),
    )
    blocks = assign_heading_paths([heading("Doc", 1), para(words(100)), table])
    chunks = chunk_blocks(blocks, ChunkingConfig(target_tokens=80, max_tokens=600), counter)

    holders = [c for c in chunks if "| r0 |" in c.text]
    assert len(holders) == 1
    assert "| r14 |" in holders[0].text


def test_code_is_re_fenced_in_rendered_output() -> None:
    rendered = render_block(code("x = 1", lang="python"))
    assert rendered == "```python\nx = 1\n```"


# ---------------------------------------------------------------------------
# Heading paths and prefixes
# ---------------------------------------------------------------------------
def test_chunk_carries_the_heading_path_of_its_first_block() -> None:
    blocks = assign_heading_paths([heading("Doc", 1), heading("Auth", 2), para("body text here")])
    chunks = chunk_blocks(blocks, None, counter)
    assert chunks[0].heading_path == ("Doc", "Auth")


def test_embed_text_is_prefixed_with_ancestors() -> None:
    text = "## Auth\n\nbody"
    embedded = build_embed_text(text, ("Doc", "Auth"), include_prefix=True)
    # Leaf is not repeated - the body already opens with it.
    assert embedded.startswith("Doc\n\n")
    assert embedded.count("Auth") == 1


def test_embed_text_includes_full_trail_when_body_has_no_heading() -> None:
    embedded = build_embed_text("plain body", ("Doc", "Auth"), include_prefix=True)
    assert embedded == "Doc > Auth\n\nplain body"


def test_embed_prefix_can_be_disabled() -> None:
    assert build_embed_text("body", ("Doc",), include_prefix=False) == "body"


def test_no_prefix_when_there_is_no_heading() -> None:
    assert build_embed_text("body", (), include_prefix=True) == "body"


def test_heading_only_buffer_never_becomes_its_own_chunk() -> None:
    blocks = assign_heading_paths(
        [heading("Doc", 1), heading("Empty Section", 2), heading("Real", 2), para("body")]
    )
    chunks = chunk_blocks(blocks, None, counter)
    assert len(chunks) == 1
    # The dangling headings ride along with the content they introduce.
    assert "Real" in chunks[0].text


# ---------------------------------------------------------------------------
# Section breaks and overlap
# ---------------------------------------------------------------------------
def test_level_two_heading_forces_a_new_chunk() -> None:
    # Bodies must exceed min_chunk_tokens, or the stub-merge legitimately folds
    # the second section back into the first (see the stub-merge test below).
    blocks = assign_heading_paths(
        [
            heading("Doc", 1),
            heading("First", 2),
            para("first " + words(60)),
            heading("Second", 2),
            para("second " + words(60)),
        ]
    )
    chunks = chunk_blocks(blocks, ChunkingConfig(target_tokens=5000, max_tokens=6000), counter)
    assert len(chunks) == 2
    assert chunks[0].heading_path == ("Doc", "First")
    assert chunks[1].heading_path == ("Doc", "Second")


def test_break_level_is_configurable() -> None:
    blocks = assign_heading_paths(
        [heading("Doc", 1), heading("A", 2), para("a"), heading("B", 2), para("b")]
    )
    merged = chunk_blocks(
        blocks, ChunkingConfig(target_tokens=5000, break_on_heading_level=1), counter
    )
    assert len(merged) == 1


def test_overlap_does_not_cross_a_section_boundary() -> None:
    # Section bodies must exceed min_chunk_tokens or the stub-merge folds them
    # back together and there is no boundary left to test.
    blocks = assign_heading_paths(
        [
            heading("Doc", 1),
            heading("First", 2),
            para("UNIQUEMARKER " + words(60)),
            heading("Second", 2),
            para("different content entirely " + words(60)),
        ]
    )
    chunks = chunk_blocks(
        blocks, ChunkingConfig(target_tokens=5, max_tokens=400, overlap_tokens=200), counter
    )
    second = next(c for c in chunks if c.heading_path[-1] == "Second")
    assert "UNIQUEMARKER" not in second.text


def test_overlap_carries_prose_within_a_section() -> None:
    # Paragraphs must be individually smaller than the overlap budget, or
    # nothing can be carried - that is the intended behaviour, not a bug.
    blocks = assign_heading_paths(
        [heading("Doc", 1)] + [para(f"sentence number {i} " + words(12)) for i in range(10)]
    )
    with_overlap = chunk_blocks(
        blocks, ChunkingConfig(target_tokens=60, max_tokens=200, overlap_tokens=60), counter
    )
    assert len(with_overlap) > 1
    assert any(c.has_overlap for c in with_overlap[1:])


def test_overlap_never_duplicates_a_code_block() -> None:
    blocks = assign_heading_paths(
        [
            heading("Doc", 1),
            para(words(40)),
            code("secret_marker = 1"),
            para(words(40)),
            para(words(40)),
        ]
    )
    chunks = chunk_blocks(
        blocks, ChunkingConfig(target_tokens=30, max_tokens=200, overlap_tokens=150), counter
    )
    occurrences = sum(c.text.count("secret_marker") for c in chunks)
    assert occurrences == 1


def test_overlap_can_be_disabled() -> None:
    blocks = assign_heading_paths([heading("Doc", 1)] + [para(words(50)) for _ in range(6)])
    chunks = chunk_blocks(
        blocks, ChunkingConfig(target_tokens=60, max_tokens=200, overlap_tokens=0), counter
    )
    assert not any(c.has_overlap for c in chunks)


# ---------------------------------------------------------------------------
# Housekeeping
# ---------------------------------------------------------------------------
def test_chunk_indices_are_contiguous_from_zero() -> None:
    blocks = assign_heading_paths([heading("Doc", 1)] + [para(words(80)) for _ in range(10)])
    chunks = chunk_blocks(blocks, ChunkingConfig(target_tokens=100, max_tokens=250), counter)
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_chunking_is_deterministic() -> None:
    blocks = assign_heading_paths([heading("Doc", 1)] + [para(words(70)) for _ in range(12)])
    config = ChunkingConfig(target_tokens=150, max_tokens=400)
    first = chunk_blocks(blocks, config, counter)
    second = chunk_blocks(blocks, config, counter)
    assert [(c.index, c.text, c.token_count) for c in first] == [
        (c.index, c.text, c.token_count) for c in second
    ]


def test_tiny_trailing_chunk_is_merged_backwards() -> None:
    blocks = assign_heading_paths(
        [heading("Doc", 1), para(words(120)), heading("Revision History", 2), para("v1")]
    )
    chunks = chunk_blocks(
        blocks, ChunkingConfig(target_tokens=100, max_tokens=600, min_chunk_tokens=40), counter
    )
    assert all(c.token_count >= 40 for c in chunks)
    assert "Revision History" in chunks[-1].text


def test_rule_blocks_are_dropped() -> None:
    blocks = assign_heading_paths(
        [heading("Doc", 1), Block(type=BlockType.RULE, text="---"), para("body")]
    )
    chunks = chunk_blocks(blocks, None, counter)
    assert "---" not in chunks[0].text


def test_line_ranges_are_recorded() -> None:
    blocks = assign_heading_paths(
        [
            Block(type=BlockType.HEADING, text="Doc", level=1, line_start=1, line_end=1),
            Block(type=BlockType.PARAGRAPH, text="body", line_start=3, line_end=5),
        ]
    )
    chunk = chunk_blocks(blocks, None, counter)[0]
    assert chunk.line_start == 1
    assert chunk.line_end == 5


@pytest.mark.parametrize("target,maximum", [(100, 200), (450, 700), (800, 1200)])
def test_invariants_hold_across_configurations(target: int, maximum: int) -> None:
    blocks = assign_heading_paths(
        [heading("Doc", 1)]
        + [para(words(90)) for _ in range(8)]
        + [code("\n".join(f"x{i} = {i}" for i in range(10)))]
        + [para(words(90)) for _ in range(8)]
    )
    config = ChunkingConfig(target_tokens=target, max_tokens=maximum)
    for chunk in chunk_blocks(blocks, config, counter):
        assert chunk.token_count <= maximum or chunk.is_split_block
        assert chunk.text.count("```") % 2 == 0
