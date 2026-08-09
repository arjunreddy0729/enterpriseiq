"""Plain text -> Blocks.

Plain text has no markup, so structure has to be inferred. Doing nothing -
treating the whole file as one paragraph - would be defensible but wasteful:
the operational handbooks people actually keep as .txt are full of implicit
structure, and throwing it away means every chunk from those files carries an
empty heading path.

Two conventions cover almost all real internal .txt files, and both appear in
this project's corpus:

    ALL CAPS SECTION HEADER          <- treated as a level-2 heading
    -------------------------        <- underline, absorbed into the heading

    Indented or blank-line-separated runs of text  <- paragraphs

The heading heuristic is deliberately conservative. A line qualifies only if it
is short, has no terminal punctuation, contains at least one letter, and is
entirely upper case. "SEE ALSO" qualifies; "THE PAGER WILL FIRE." does not.
False positives here are worse than false negatives - a wrongly promoted line
becomes a section boundary and splits a chunk in the wrong place.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.ingestion.blocks import Block, BlockType, ParsedDocument, assign_heading_paths
from app.ingestion.parsers.base import ParserError, derive_title

#: Maximum characters for a line to be considered a section header.
_MAX_HEADING_LEN = 72

_UNDERLINE = re.compile(r"^\s*(?:[-=_*]{3,})\s*$")
_HAS_LETTER = re.compile(r"[A-Za-z]")
_TERMINAL_PUNCT = (".", ",", ";", ":", "!", "?")


def looks_like_heading(line: str) -> bool:
    """Conservative ALL-CAPS section-header test."""
    stripped = line.strip()
    if not stripped or len(stripped) > _MAX_HEADING_LEN:
        return False
    if not _HAS_LETTER.search(stripped):
        return False
    if stripped.endswith(_TERMINAL_PUNCT):
        return False
    # Bullets and numbered items are content, not headers.
    if re.match(r"^(?:[-*+•]|\d+[.)])\s", stripped):
        return False
    return stripped == stripped.upper()


class TextParser:
    """Parses `.txt` / `.text` / `.log` into blocks."""

    extensions = (".txt", ".text", ".log")
    source_type = "txt"

    def parse(self, path: Path) -> ParsedDocument:
        try:
            raw = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # Operational text files are frequently latin-1. Retry once rather
            # than failing an ingest over an encoding guess.
            try:
                raw = path.read_text(encoding="latin-1")
            except OSError as exc:
                raise ParserError(path, f"could not be read: {exc}") from exc
        except OSError as exc:
            raise ParserError(path, f"could not be read: {exc}") from exc

        blocks = self.parse_text(raw)
        assign_heading_paths(blocks)

        first_heading = next((b.text for b in blocks if b.is_heading), None)
        return ParsedDocument(
            title=derive_title(path, first_heading),
            blocks=blocks,
            source_type=self.source_type,
            source_uri=str(path),
            metadata={"line_count": raw.count("\n") + 1, "block_count": len(blocks)},
        )

    def parse_text(self, raw: str) -> list[Block]:
        lines = raw.splitlines()
        blocks: list[Block] = []
        buffer: list[str] = []
        buffer_start = 0

        def flush(end_line: int) -> None:
            nonlocal buffer, buffer_start
            if not buffer:
                return
            text = "\n".join(buffer).strip()
            if text:
                blocks.append(
                    Block(
                        type=BlockType.PARAGRAPH,
                        text=text,
                        line_start=buffer_start + 1,
                        line_end=end_line,
                    )
                )
            buffer = []

        i = 0
        n = len(lines)
        while i < n:
            line = lines[i]

            if not line.strip():
                flush(i)
                i += 1
                continue

            if looks_like_heading(line):
                flush(i)
                end = i + 1
                # Absorb an underline so it does not become a stray paragraph.
                if end < n and _UNDERLINE.match(lines[end]):
                    end += 1
                blocks.append(
                    Block(
                        type=BlockType.HEADING,
                        text=line.strip(),
                        level=2,
                        line_start=i + 1,
                        line_end=end,
                    )
                )
                i = end
                continue

            if not buffer:
                buffer_start = i
            buffer.append(line)
            i += 1

        flush(n)
        return blocks
