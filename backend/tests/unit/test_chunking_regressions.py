"""Regression tests for defects found by the adversarial audit of the chunker.

Every test here corresponds to a bug that shipped and was caught by an
independent review pass, not by the tests written alongside the code. Several
of them exist because the original test for the same guarantee was hollow -
it passed against a deliberately broken copy of the source.

Where a test is guarding against a hollow predecessor, it says so.
"""

from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings
from app.ingestion.blocks import Block, BlockType, assign_heading_paths
from app.ingestion.chunking import ChunkingConfig, chunk_blocks
from app.ingestion.parsers import parse_file
from app.ingestion.parsers.markdown import MarkdownParser
from app.ingestion.tokens import HeuristicTokenCounter

counter = HeuristicTokenCounter()
markdown = MarkdownParser()


def heading(text: str, level: int = 2) -> Block:
    return Block(type=BlockType.HEADING, text=text, level=level)


def para(text: str) -> Block:
    return Block(type=BlockType.PARAGRAPH, text=text)


def words(n: int) -> str:
    return " ".join(["alpha"] * n)


def sized(tokens: int) -> Block:
    """A paragraph of approximately `tokens` heuristic tokens."""
    return para(words(max(1, round(tokens / 1.58))))


# ---------------------------------------------------------------------------
# Content loss - the failure mode an ingestion pipeline must never have
# ---------------------------------------------------------------------------
def test_trailing_headings_are_not_dropped() -> None:
    """A document ending in headings used to lose them silently."""
    blocks = assign_heading_paths(
        [
            heading("Vendor Policy", 1),
            sized(120),
            heading("Appendix A: Escalation Contacts", 2),
            heading("Appendix B: Glossary", 2),
        ]
    )
    text = " ".join(c.text for c in chunk_blocks(blocks, None, counter))
    assert "Appendix A: Escalation Contacts" in text
    assert "Appendix B: Glossary" in text


def test_heading_only_document_still_produces_chunks() -> None:
    """An index/table-of-contents page used to produce zero chunks."""
    blocks = assign_heading_paths(
        [
            heading("Employee Handbook Index", 1),
            heading("Section 1 Onboarding", 2),
            heading("Section 2 Benefits", 2),
            heading("Section 3 Payroll", 2),
        ]
    )
    chunks = chunk_blocks(blocks, None, counter)
    assert chunks, "a heading-only document must not vanish"
    combined = " ".join(c.text for c in chunks)
    for title in ("Section 1 Onboarding", "Section 2 Benefits", "Section 3 Payroll"):
        assert title in combined


def test_no_block_text_is_lost_across_the_corpus() -> None:
    """Every parsed block must appear in some chunk."""
    corpus = get_settings().corpus_dir
    if not corpus.is_dir():
        return
    for path in sorted(corpus.rglob("*.md")):
        document = parse_file(path)
        combined = "\n".join(c.text for c in chunk_blocks(document.blocks, None, counter))
        for block in document.blocks:
            if block.type is BlockType.RULE or not block.text.strip():
                continue
            probe = block.text.strip().splitlines()[0][:60]
            assert probe in combined, f"{path.name}: lost {probe!r}"


# ---------------------------------------------------------------------------
# The ceiling is a guarantee
# ---------------------------------------------------------------------------
def test_ceiling_flush_path_is_actually_reached() -> None:
    """The overflow branch had zero coverage: deleting it kept the suite green.

    Two blocks that each fit but together exceed the ceiling, with the first
    landing below the target so the target flush cannot fire first.
    """
    config = ChunkingConfig(target_tokens=450, max_tokens=700, overlap_tokens=0)
    blocks = assign_heading_paths([heading("Doc", 1), sized(399), sized(394)])
    chunks = chunk_blocks(blocks, config, counter)
    assert len(chunks) == 2
    for chunk in chunks:
        assert chunk.token_count <= config.max_tokens


def test_overlap_cannot_push_a_chunk_over_the_ceiling() -> None:
    """Overlap re-seeding used to bypass the ceiling check entirely.

    The original size test pinned overlap_tokens=0, disabling the only code
    path that caused the breach.
    """
    config = ChunkingConfig(target_tokens=450, max_tokens=700, overlap_tokens=60)
    blocks = assign_heading_paths([heading("Doc", 1), sized(120), sized(34), sized(660)])
    for chunk in chunk_blocks(blocks, config, counter):
        assert chunk.token_count <= config.max_tokens or chunk.is_split_block


def test_heading_prefix_is_charged_to_the_packing_budget() -> None:
    """token_count included the heading prefix; the packing loop did not."""
    deep = ("Employee Performance Review Process", "Performance Improvement Plans", "Outcomes")
    blocks = [
        Block(type=BlockType.PARAGRAPH, text=words(250), heading_path=deep),
        Block(type=BlockType.PARAGRAPH, text=words(250), heading_path=deep),
    ]
    config = ChunkingConfig(target_tokens=450, max_tokens=700, overlap_tokens=0)
    for chunk in chunk_blocks(blocks, config, counter):
        assert chunk.token_count <= config.max_tokens or chunk.is_split_block


# ---------------------------------------------------------------------------
# Overlap behaviour
# ---------------------------------------------------------------------------
def test_a_chunk_is_never_pure_duplicated_overlap() -> None:
    """Overlap seeding could emit a chunk containing no new content at all."""
    blocks = assign_heading_paths(
        [
            heading("Doc", 1),
            heading("First", 2),
            sized(60),
            para("MARKER tail sentence that will be carried forward"),
            heading("Second", 2),
            sized(60),
        ]
    )
    chunks = chunk_blocks(
        blocks,
        ChunkingConfig(target_tokens=70, max_tokens=400, overlap_tokens=80),
        counter,
    )
    for i, chunk in enumerate(chunks):
        for other in chunks[:i]:
            assert chunk.text not in other.text, f"chunk {i} is wholly duplicated"


def test_overlap_seeded_chunk_is_labelled_with_its_own_section() -> None:
    """The label used to name the section the overlap came from."""
    blocks = assign_heading_paths(
        [
            heading("Doc", 1),
            heading("Old Section", 3),
            sized(60),
            para("carried tail sentence"),
            heading("New Section", 3),
            sized(60),
        ]
    )
    chunks = chunk_blocks(
        blocks,
        ChunkingConfig(target_tokens=70, max_tokens=400, overlap_tokens=80),
        counter,
    )
    for chunk in chunks:
        if "New Section" in chunk.text:
            assert chunk.heading_path[-1] == "New Section"


# ---------------------------------------------------------------------------
# Guarantees whose tests were hollow
# ---------------------------------------------------------------------------
def test_break_level_changes_the_outcome_in_both_directions() -> None:
    """The old test passed at every break level, so the knob was dead config."""
    blocks = assign_heading_paths(
        [heading("Doc", 1), heading("A", 2), sized(80), heading("B", 2), sized(80)]
    )
    at_one = chunk_blocks(
        blocks,
        ChunkingConfig(target_tokens=5000, max_tokens=6000, break_on_heading_level=1),
        counter,
    )
    at_two = chunk_blocks(
        blocks,
        ChunkingConfig(target_tokens=5000, max_tokens=6000, break_on_heading_level=2),
        counter,
    )
    assert len(at_one) == 1
    assert len(at_two) == 2


def test_chunks_actually_carry_the_heading_prefix() -> None:
    """Removing the prefix from every chunk used to keep the suite green.

    The old corpus assertion was `chunk.text in chunk.embed_text`, which holds
    trivially when the two are identical.
    """
    blocks = assign_heading_paths(
        [heading("Payments", 1), heading("Auth", 2), para("plain body sentence")]
    )
    chunk = chunk_blocks(blocks, None, counter)[0]
    assert chunk.embed_text != chunk.text
    # Full trail, because the body opens with the H1 rather than the leaf, so
    # the leaf-deduplication does not apply.
    assert chunk.embed_text.startswith("Payments > Auth\n\n")


def test_prefix_can_be_turned_off_at_the_chunk_level() -> None:
    blocks = assign_heading_paths([heading("Doc", 1), para("body")])
    chunk = chunk_blocks(blocks, ChunkingConfig(include_heading_prefix=False), counter)[0]
    assert chunk.embed_text == chunk.text


# ---------------------------------------------------------------------------
# Oversized atomic blocks - G2's stated exemption, previously untested
# ---------------------------------------------------------------------------
def test_oversized_code_block_fragments_stay_valid_and_flagged() -> None:
    body = "\n".join(f"variable_{i} = compute_something({i})" for i in range(400))
    blocks = assign_heading_paths(
        [heading("Doc", 1), Block(type=BlockType.CODE, text=body, lang="python")]
    )
    chunks = chunk_blocks(blocks, None, counter)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.is_split_block
        assert chunk.text.count("```") % 2 == 0


def test_oversized_table_repeats_its_header_on_every_fragment() -> None:
    rows = ["| region | vendor | tier | spend |", "| --- | --- | --- | --- |"]
    rows += [f"| eu-west-{i} | vendor_{i} | tier_{i % 3} | {i * 1000} |" for i in range(300)]
    blocks = assign_heading_paths(
        [heading("Vendors", 1), Block(type=BlockType.TABLE, text="\n".join(rows))]
    )
    chunks = chunk_blocks(blocks, None, counter)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.is_split_block
        assert "| region | vendor | tier | spend |" in chunk.text


# ---------------------------------------------------------------------------
# Configuration must have one source of truth
# ---------------------------------------------------------------------------
def test_chunking_config_defaults_track_settings() -> None:
    settings = get_settings()
    config = ChunkingConfig.from_settings()
    assert config.target_tokens == settings.chunk_target_tokens
    assert config.max_tokens == settings.chunk_max_tokens
    assert config.overlap_tokens == settings.chunk_overlap_tokens


def test_chunk_blocks_defaults_to_settings_derived_config() -> None:
    blocks = assign_heading_paths([heading("Doc", 1), sized(50)])
    assert chunk_blocks(blocks, None, counter) == chunk_blocks(
        blocks, ChunkingConfig.from_settings(), counter
    )


# ---------------------------------------------------------------------------
# Parser: decorated code fences
# ---------------------------------------------------------------------------
def test_fence_with_an_info_string_is_still_a_fence() -> None:
    """A decorated fence was not recognised, so the parser swallowed the rest
    of the document - headings and all - into one code block."""
    source = '```python title="example.py" linenums\nx = 1\n```\n\n# Real Heading\n\nbody\n'
    blocks = markdown.parse_text(source)
    kinds = [b.type for b in blocks]
    assert BlockType.HEADING in kinds
    assert blocks[0].type is BlockType.CODE
    assert blocks[0].lang == "python"
    assert any(b.text == "Real Heading" for b in blocks)


def test_fence_with_brace_info_string() -> None:
    source = "```{.bash .numberLines}\necho hi\n```\n\n## After\n\nbody\n"
    blocks = markdown.parse_text(source)
    assert blocks[0].type is BlockType.CODE
    assert any(b.type is BlockType.HEADING and b.text == "After" for b in blocks)


def test_decorated_fence_end_to_end(tmp_path: Path) -> None:
    path = tmp_path / "doc.md"
    path.write_text(
        '# Guide\n\n```yaml title="deploy.yml"\nkey: value\n```\n\n## Section Two\n\nbody\n',
        encoding="utf-8",
    )
    document = parse_file(path)
    assert any(b.text == "Section Two" for b in document.blocks)
