"""DOCX -> Blocks, via python-docx.

Word documents are the easy case: unlike PDFs, they carry real structure.
Paragraph styles named `Heading 1`..`Heading 9` give heading levels directly,
and tables are first-class objects rather than visually-aligned text.

Two details that a naive implementation gets wrong:

1. **Body order.** `document.paragraphs` and `document.tables` are separate
   collections, so iterating them in turn interleaves the document wrongly -
   every table ends up after every paragraph. The fix is to walk the body XML
   element order and dispatch on tag name, which is what `_iter_body` does.

2. **Style naming.** Heading styles are localised and templates rename them,
   so `style.name == "Heading 1"` is fragile. We check `style_id` too, which
   stays `Heading1` regardless of display name.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.ingestion.blocks import Block, BlockType, ParsedDocument, assign_heading_paths
from app.ingestion.parsers.base import ParserError, derive_title

_HEADING_STYLE = re.compile(r"^heading\s*([1-9])$", re.IGNORECASE)
_LIST_STYLE = re.compile(r"list|bullet", re.IGNORECASE)


class DocxParser:
    """Parses `.docx` into blocks using Word's own paragraph styles."""

    extensions = (".docx",)
    source_type = "docx"

    def parse(self, path: Path) -> ParsedDocument:
        try:
            import docx  # type: ignore[import-not-found]
            from docx.table import Table
            from docx.text.paragraph import Paragraph
        except ImportError as exc:  # pragma: no cover - optional extra
            raise ParserError(
                path, "DOCX support needs the 'parsers' extra: pip install '.[parsers]'"
            ) from exc

        try:
            document = docx.Document(str(path))
        except Exception as exc:
            raise ParserError(path, f"could not be opened as a .docx: {exc}") from exc

        blocks: list[Block] = []
        for item in self._iter_body(document, Paragraph, Table):
            if isinstance(item, Paragraph):
                block = self._paragraph_to_block(item)
                if block is not None:
                    blocks.append(block)
            else:
                block = self._table_to_block(item)
                if block is not None:
                    blocks.append(block)

        assign_heading_paths(blocks)

        core = document.core_properties
        docx_title = (core.title or "").strip() or None
        first_heading = next((b.text for b in blocks if b.is_heading), None)

        return ParsedDocument(
            title=derive_title(path, docx_title or first_heading),
            blocks=blocks,
            source_type=self.source_type,
            source_uri=str(path),
            metadata={
                "block_count": len(blocks),
                "author": (core.author or "").strip() or None,
            },
        )

    # -- helpers ------------------------------------------------------------
    def _iter_body(self, document: Any, paragraph_cls: Any, table_cls: Any) -> Any:
        """Yield paragraphs and tables in true document order."""
        body = document.element.body
        for child in body.iterchildren():
            tag = child.tag.split("}")[-1]
            if tag == "p":
                yield paragraph_cls(child, document)
            elif tag == "tbl":
                yield table_cls(child, document)

    def _paragraph_to_block(self, paragraph: Any) -> Block | None:
        text = (paragraph.text or "").strip()
        if not text:
            return None

        style = paragraph.style
        style_name = (getattr(style, "name", "") or "").strip()
        style_id = (getattr(style, "style_id", "") or "").strip()

        match = _HEADING_STYLE.match(style_name) or _HEADING_STYLE.match(style_id)
        if match:
            return Block(type=BlockType.HEADING, text=text, level=int(match.group(1)))

        if style_name.lower() == "title" or style_id.lower() == "title":
            return Block(type=BlockType.HEADING, text=text, level=1)

        if _LIST_STYLE.search(style_name) or _LIST_STYLE.search(style_id):
            return Block(type=BlockType.LIST, text=text)

        return Block(type=BlockType.PARAGRAPH, text=text)

    def _table_to_block(self, table: Any) -> Block | None:
        """Render a table as pipe-delimited text.

        Pipe form is chosen so that DOCX tables, Markdown tables and (later)
        PDF tables all reach the chunker and the embedding model in the same
        shape. One representation means one set of retrieval behaviour.
        """
        rows: list[str] = []
        for row in table.rows:
            cells = [(cell.text or "").strip().replace("\n", " ") for cell in row.cells]
            if any(cells):
                rows.append("| " + " | ".join(cells) + " |")
        if not rows:
            return None
        return Block(type=BlockType.TABLE, text="\n".join(rows))
