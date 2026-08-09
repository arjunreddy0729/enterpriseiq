"""Markdown -> Blocks.

This is a hand-written line scanner rather than markdown-it-py, and that is a
deliberate choice worth defending.

A Markdown library gives you either an HTML render or a token stream aimed at
producing one. We do not want HTML. We want *block structure with source line
numbers*, and specifically we want fenced code and tables to survive as single
indivisible units. Getting that out of a token stream means walking it and
reassembling the original source text anyway - which is most of this file,
plus a dependency, plus the risk that a renderer-oriented library silently
normalises the text we are about to embed.

The grammar we actually need is small and closed:

    ATX heading      # .. ######
    fenced code      ``` or ~~~ , optional language tag
    table            contiguous lines beginning with |
    blockquote       contiguous lines beginning with >
    list             contiguous lines beginning with -, *, + or `1.`
    thematic break   ---, ***, ___
    paragraph        anything else, terminated by a blank line

Fences take absolute precedence: a `#` inside a code block is code, not a
heading. That single rule is the one most naive splitters get wrong, and it is
why chunk boundaries land inside YAML examples in so many RAG demos.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.ingestion.blocks import Block, BlockType, ParsedDocument, assign_heading_paths
from app.ingestion.parsers.base import ParserError, derive_title

_ATX_HEADING = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<text>.*?)\s*#*\s*$")
# The info string after a fence is free-form: ```python, ```py title="x",
# ```{.bash .numberLines}. Matching only a bare word meant a decorated fence
# was not recognised as a fence at all, so the scanner kept reading and
# swallowed the entire rest of the document - headings included - into one
# code block. Accept anything, then take the first word as the language.
_FENCE = re.compile(r"^(?P<indent>\s{0,3})(?P<fence>```+|~~~+)(?P<info>[^`]*)$")
_TABLE_ROW = re.compile(r"^\s{0,3}\|")
_QUOTE = re.compile(r"^\s{0,3}>")
_LIST_ITEM = re.compile(r"^\s{0,3}(?:[-*+]\s+|\d{1,9}[.)]\s+)")
_THEMATIC_BREAK = re.compile(r"^\s{0,3}(?:-{3,}|\*{3,}|_{3,})\s*$")
# `Heading` followed by `=====` or `-----` (setext form). Rare in our corpus but
# cheap to support, and mis-reading one as a thematic break would silently drop
# a heading from every path beneath it.
_SETEXT_UNDERLINE = re.compile(r"^\s{0,3}(?P<char>=+|-+)\s*$")


class MarkdownParser:
    """Parses `.md` / `.markdown` into blocks."""

    extensions = (".md", ".markdown")
    source_type = "markdown"

    def parse(self, path: Path) -> ParsedDocument:
        try:
            raw = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ParserError(path, f"not valid UTF-8: {exc}") from exc
        except OSError as exc:
            raise ParserError(path, f"could not be read: {exc}") from exc

        blocks = self.parse_text(raw)
        assign_heading_paths(blocks)

        first_heading = next(
            (b.text for b in blocks if b.type is BlockType.HEADING and b.level == 1),
            None,
        )
        if first_heading is None:
            first_heading = next(
                (b.text for b in blocks if b.type is BlockType.HEADING), None
            )

        return ParsedDocument(
            title=derive_title(path, first_heading),
            blocks=blocks,
            source_type=self.source_type,
            source_uri=str(path),
            metadata={
                "line_count": raw.count("\n") + 1,
                "block_count": len(blocks),
            },
        )

    # -- the scanner --------------------------------------------------------
    def parse_text(self, raw: str) -> list[Block]:
        """Split Markdown source into blocks. Pure function, easy to test."""
        lines = raw.splitlines()
        blocks: list[Block] = []
        i = 0
        n = len(lines)

        while i < n:
            line = lines[i]
            lineno = i + 1

            # Blank lines separate blocks and carry no content.
            if not line.strip():
                i += 1
                continue

            # --- fenced code: highest precedence -------------------------
            fence = _FENCE.match(line)
            if fence:
                marker = fence.group("fence")
                info = (fence.group("info") or "").strip()
                lang = info.split()[0] if info else None
                body: list[str] = []
                i += 1
                closed = False
                while i < n:
                    # A closing fence must be the same character, at least as long.
                    candidate = lines[i].strip()
                    if candidate.startswith(marker[0] * len(marker)) and set(
                        candidate
                    ) <= set(marker[0]):
                        closed = True
                        i += 1
                        break
                    body.append(lines[i])
                    i += 1
                text = "\n".join(body)
                blocks.append(
                    Block(
                        type=BlockType.CODE,
                        text=text,
                        lang=lang,
                        line_start=lineno,
                        line_end=i,
                    )
                )
                # An unterminated fence consumed to EOF. That is recorded by
                # `closed` for a future diagnostic, but deliberately not raised:
                # one malformed document must not fail an ingest of four hundred,
                # and the content is still perfectly retrievable.
                del closed
                continue

            # --- ATX heading ---------------------------------------------
            heading = _ATX_HEADING.match(line)
            if heading:
                blocks.append(
                    Block(
                        type=BlockType.HEADING,
                        text=heading.group("text").strip(),
                        level=len(heading.group("hashes")),
                        line_start=lineno,
                        line_end=lineno,
                    )
                )
                i += 1
                continue

            # --- thematic break ------------------------------------------
            # A `---` reached here is always a break, never a setext underline:
            # an underline is only reachable from inside the paragraph branch,
            # which consumes the text line and the underline together.
            if _THEMATIC_BREAK.match(line):
                blocks.append(
                    Block(
                        type=BlockType.RULE, text="---", line_start=lineno, line_end=lineno
                    )
                )
                i += 1
                continue

            # --- table ----------------------------------------------------
            if _TABLE_ROW.match(line):
                start = i
                while i < n and _TABLE_ROW.match(lines[i]):
                    i += 1
                blocks.append(
                    Block(
                        type=BlockType.TABLE,
                        text="\n".join(lines[start:i]),
                        line_start=start + 1,
                        line_end=i,
                    )
                )
                continue

            # --- blockquote ----------------------------------------------
            if _QUOTE.match(line):
                start = i
                # Only '>' lines. Lazy continuation is legal Markdown but
                # consuming non-'>' lines here would swallow a heading that
                # follows the quote without a blank line, and a swallowed
                # heading corrupts the heading_path of everything beneath it.
                while i < n and _QUOTE.match(lines[i]):
                    i += 1
                blocks.append(
                    Block(
                        type=BlockType.QUOTE,
                        text="\n".join(lines[start:i]),
                        line_start=start + 1,
                        line_end=i,
                    )
                )
                continue

            # --- list -----------------------------------------------------
            if _LIST_ITEM.match(line):
                start = i
                # A list runs until a blank line that is followed by something
                # which is not a list item or an indented continuation.
                while i < n:
                    current = lines[i]
                    if current.strip():
                        # A heading or fence terminates the list even without a
                        # blank line before it - same reasoning as blockquotes.
                        if i > start and (
                            _ATX_HEADING.match(current) or _FENCE.match(current)
                        ):
                            break
                        i += 1
                        continue
                    lookahead = i + 1
                    while lookahead < n and not lines[lookahead].strip():
                        lookahead += 1
                    if lookahead < n and (
                        _LIST_ITEM.match(lines[lookahead])
                        or lines[lookahead].startswith(("  ", "\t"))
                    ):
                        i = lookahead
                        continue
                    break
                blocks.append(
                    Block(
                        type=BlockType.LIST,
                        text="\n".join(lines[start:i]).rstrip(),
                        line_start=start + 1,
                        line_end=i,
                    )
                )
                continue

            # --- paragraph (with setext heading detection) ----------------
            start = i
            para: list[str] = []
            while i < n and lines[i].strip():
                # Stop if the next construct starts here.
                if i > start and (
                    _ATX_HEADING.match(lines[i])
                    or _FENCE.match(lines[i])
                    or _TABLE_ROW.match(lines[i])
                    or _LIST_ITEM.match(lines[i])
                ):
                    break
                setext = _SETEXT_UNDERLINE.match(lines[i])
                if setext and para:
                    level = 1 if setext.group("char").startswith("=") else 2
                    blocks.append(
                        Block(
                            type=BlockType.HEADING,
                            text=" ".join(p.strip() for p in para).strip(),
                            level=level,
                            line_start=start + 1,
                            line_end=i + 1,
                        )
                    )
                    para = []
                    i += 1
                    break
                para.append(lines[i])
                i += 1

            if para:
                blocks.append(
                    Block(
                        type=BlockType.PARAGRAPH,
                        text=" ".join(p.strip() for p in para).strip(),
                        line_start=start + 1,
                        line_end=i,
                    )
                )

        return blocks
