"""Plain-text parser and its ALL-CAPS heading heuristic.

False positives are worse than false negatives here: a wrongly promoted line
becomes a section boundary and splits a chunk in the wrong place.
"""

from __future__ import annotations

from pathlib import Path

from app.ingestion.blocks import BlockType
from app.ingestion.parsers.text import TextParser, looks_like_heading

parser = TextParser()


def test_all_caps_line_is_a_heading() -> None:
    assert looks_like_heading("ESCALATION LADDER")
    assert looks_like_heading("HANDOFF CHECKLIST")


def test_sentence_case_is_not_a_heading() -> None:
    assert not looks_like_heading("The primary carries the pager.")


def test_all_caps_sentence_with_terminal_punctuation_is_not_a_heading() -> None:
    assert not looks_like_heading("THE PAGER WILL FIRE.")


def test_long_all_caps_line_is_not_a_heading() -> None:
    assert not looks_like_heading("THIS LINE IS FAR TOO LONG TO BE A SECTION HEADER " * 3)


def test_bullets_are_not_headings() -> None:
    assert not looks_like_heading("- ITEM ONE")
    assert not looks_like_heading("1. ITEM ONE")


def test_lines_without_letters_are_not_headings() -> None:
    assert not looks_like_heading("--------")
    assert not looks_like_heading("12345")
    assert not looks_like_heading("")


def test_underline_is_absorbed_into_the_heading() -> None:
    blocks = parser.parse_text("SECTION ONE\n-----------\n\nbody text\n")
    assert [b.type for b in blocks] == [BlockType.HEADING, BlockType.PARAGRAPH]
    assert blocks[0].text == "SECTION ONE"


def test_paragraphs_split_on_blank_lines() -> None:
    blocks = parser.parse_text("first para\nstill first\n\nsecond para\n")
    assert len(blocks) == 2
    assert blocks[0].text == "first para\nstill first"


def test_heading_paths_are_assigned(tmp_path: Path) -> None:
    path = tmp_path / "handbook.txt"
    path.write_text("ROTATION\n\nWeekly rotation.\n\nESCALATION\n\nPage the IC.\n", encoding="utf-8")
    document = parser.parse(path)
    bodies = [b for b in document.blocks if b.type is BlockType.PARAGRAPH]
    assert bodies[0].heading_path == ("ROTATION",)
    assert bodies[1].heading_path == ("ESCALATION",)


def test_title_falls_back_to_filename(tmp_path: Path) -> None:
    path = tmp_path / "oncall-rotation.txt"
    path.write_text("just body text\n", encoding="utf-8")
    assert parser.parse(path).title == "Oncall Rotation"


def test_latin1_file_does_not_raise(tmp_path: Path) -> None:
    path = tmp_path / "legacy.txt"
    path.write_bytes("caf\xe9 notes\n".encode("latin-1"))
    document = parser.parse(path)
    assert document.blocks
