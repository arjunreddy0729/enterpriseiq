"""Markdown block scanner.

The cases here are the ones that actually break naive splitters: a `#` inside
a fenced code block, a heading that follows a list or quote with no blank line,
and an unterminated fence.
"""

from __future__ import annotations

from pathlib import Path

from app.ingestion.blocks import BlockType
from app.ingestion.parsers.markdown import MarkdownParser

parser = MarkdownParser()


def types(source: str) -> list[BlockType]:
    return [b.type for b in parser.parse_text(source)]


def test_headings_and_paragraphs() -> None:
    blocks = parser.parse_text("# Title\n\nSome prose.\n\n## Section\n\nMore prose.\n")
    assert [b.type for b in blocks] == [
        BlockType.HEADING,
        BlockType.PARAGRAPH,
        BlockType.HEADING,
        BlockType.PARAGRAPH,
    ]
    assert blocks[0].level == 1
    assert blocks[2].level == 2
    assert blocks[0].text == "Title"


def test_hash_inside_a_fence_is_code_not_a_heading() -> None:
    # The single most important rule in this parser.
    source = "# Real heading\n\n```bash\n# this is a shell comment\necho hi\n```\n"
    blocks = parser.parse_text(source)
    assert [b.type for b in blocks] == [BlockType.HEADING, BlockType.CODE]
    assert "# this is a shell comment" in blocks[1].text
    assert blocks[1].lang == "bash"


def test_fence_language_is_captured() -> None:
    blocks = parser.parse_text("```python\nx = 1\n```\n")
    assert blocks[0].lang == "python"
    assert blocks[0].text == "x = 1"


def test_fence_without_language() -> None:
    blocks = parser.parse_text("```\nplain\n```\n")
    assert blocks[0].type is BlockType.CODE
    assert blocks[0].lang is None


def test_tilde_fences_work() -> None:
    blocks = parser.parse_text("~~~yaml\nkey: value\n~~~\n")
    assert blocks[0].type is BlockType.CODE
    assert blocks[0].lang == "yaml"


def test_unterminated_fence_consumes_to_eof_without_raising() -> None:
    # A malformed document must not fail the ingest, and its content must
    # still be retrievable.
    blocks = parser.parse_text("```python\nx = 1\n")
    assert len(blocks) == 1
    assert blocks[0].type is BlockType.CODE
    assert blocks[0].lang == "python"
    assert "x = 1" in blocks[0].text


def test_table_is_one_block() -> None:
    source = "| a | b |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |\n"
    blocks = parser.parse_text(source)
    assert len(blocks) == 1
    assert blocks[0].type is BlockType.TABLE
    assert blocks[0].text.count("\n") == 3


def test_list_is_one_block() -> None:
    blocks = parser.parse_text("- one\n- two\n- three\n")
    assert [b.type for b in blocks] == [BlockType.LIST]


def test_heading_immediately_after_a_list_is_not_swallowed() -> None:
    # Regression: a greedy list scanner ate the heading, which corrupted the
    # heading_path of every block below it.
    blocks = parser.parse_text("- one\n- two\n# Heading\n\nbody\n")
    assert BlockType.HEADING in [b.type for b in blocks]
    heading = next(b for b in blocks if b.type is BlockType.HEADING)
    assert heading.text == "Heading"


def test_heading_immediately_after_a_quote_is_not_swallowed() -> None:
    blocks = parser.parse_text("> quoted\n# Heading\n\nbody\n")
    assert [b.type for b in blocks] == [
        BlockType.QUOTE,
        BlockType.HEADING,
        BlockType.PARAGRAPH,
    ]


def test_fence_immediately_after_a_list_is_not_swallowed() -> None:
    blocks = parser.parse_text("- one\n```py\nx=1\n```\n")
    assert BlockType.CODE in [b.type for b in blocks]


def test_thematic_break_after_blank_line() -> None:
    assert types("para\n\n---\n\nmore\n") == [
        BlockType.PARAGRAPH,
        BlockType.RULE,
        BlockType.PARAGRAPH,
    ]


def test_setext_heading_is_recognised() -> None:
    blocks = parser.parse_text("My Heading\n---\n\nbody\n")
    assert blocks[0].type is BlockType.HEADING
    assert blocks[0].level == 2
    assert blocks[0].text == "My Heading"


def test_setext_level_one() -> None:
    blocks = parser.parse_text("Title\n===\n\nbody\n")
    assert blocks[0].level == 1


def test_paragraph_lines_are_joined() -> None:
    blocks = parser.parse_text("line one\nline two\n")
    assert blocks[0].text == "line one line two"


def test_line_numbers_are_recorded() -> None:
    blocks = parser.parse_text("# Title\n\nbody\n")
    assert blocks[0].line_start == 1
    assert blocks[1].line_start == 3


def test_parse_real_file(tmp_path: Path) -> None:
    path = tmp_path / "doc.md"
    path.write_text("# Real Title\n\nbody text\n", encoding="utf-8")
    document = parser.parse(path)
    assert document.title == "Real Title"
    assert document.source_type == "markdown"
    assert len(document.blocks) == 2
    assert document.blocks[1].heading_path == ("Real Title",)


def test_title_falls_back_to_filename(tmp_path: Path) -> None:
    path = tmp_path / "adr-0007-postgres-partitioning.md"
    path.write_text("no heading here\n", encoding="utf-8")
    assert parser.parse(path).title == "Adr 0007 Postgres Partitioning"


def test_empty_document_yields_no_blocks() -> None:
    assert parser.parse_text("") == []
    assert parser.parse_text("\n\n   \n") == []
