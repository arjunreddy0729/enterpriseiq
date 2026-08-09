"""Heading-path assignment.

Heading paths are load-bearing: they are prefixed onto embedded text and
weighted 'A' in the tsvector. A wrong path silently mislabels every chunk
beneath it, so the level-stack behaviour is worth pinning down precisely.
"""

from __future__ import annotations

from app.ingestion.blocks import (
    Block,
    BlockType,
    ParsedDocument,
    assign_heading_paths,
)


def heading(text: str, level: int) -> Block:
    return Block(type=BlockType.HEADING, text=text, level=level)


def para(text: str) -> Block:
    return Block(type=BlockType.PARAGRAPH, text=text)


def test_nested_headings_build_a_trail() -> None:
    blocks = assign_heading_paths(
        [heading("Payments", 1), heading("Auth", 2), para("body")]
    )
    assert blocks[0].heading_path == ("Payments",)
    assert blocks[1].heading_path == ("Payments", "Auth")
    assert blocks[2].heading_path == ("Payments", "Auth")


def test_heading_includes_itself_in_its_path() -> None:
    # A chunk that starts at a heading should be labelled with that heading,
    # not with its parent.
    blocks = assign_heading_paths([heading("Top", 1), heading("Child", 2)])
    assert blocks[1].heading_path == ("Top", "Child")


def test_sibling_heading_replaces_previous_subtree() -> None:
    blocks = assign_heading_paths(
        [
            heading("Doc", 1),
            heading("Auth", 2),
            heading("Details", 3),
            heading("Idempotency", 2),
            para("body"),
        ]
    )
    assert blocks[-1].heading_path == ("Doc", "Idempotency")


def test_skipped_levels_do_not_break_the_stack() -> None:
    # H1 -> H3 with no H2. The H3 nests rather than replacing the H1.
    blocks = assign_heading_paths([heading("Doc", 1), heading("Deep", 3), para("x")])
    assert blocks[-1].heading_path == ("Doc", "Deep")


def test_blocks_before_any_heading_have_an_empty_path() -> None:
    blocks = assign_heading_paths([para("preamble"), heading("Doc", 1), para("after")])
    assert blocks[0].heading_path == ()
    assert blocks[2].heading_path == ("Doc",)


def test_second_h1_resets_the_trail() -> None:
    blocks = assign_heading_paths(
        [heading("First", 1), heading("Sub", 2), heading("Second", 1), para("x")]
    )
    assert blocks[-1].heading_path == ("Second",)


def test_heading_trail_renders_with_separators() -> None:
    blocks = assign_heading_paths([heading("A", 1), heading("B", 2), para("x")])
    assert blocks[-1].heading_trail == "A > B"


def test_atomic_types() -> None:
    assert Block(type=BlockType.CODE, text="x").is_atomic
    assert Block(type=BlockType.TABLE, text="x").is_atomic
    assert not Block(type=BlockType.PARAGRAPH, text="x").is_atomic


def test_parsed_document_text_joins_blocks() -> None:
    document = ParsedDocument(
        title="t",
        blocks=[para("one"), para("two")],
        source_type="markdown",
        source_uri="x.md",
    )
    assert document.text == "one\n\ntwo"
