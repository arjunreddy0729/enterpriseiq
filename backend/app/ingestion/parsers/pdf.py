"""PDF -> Blocks, via PyMuPDF.

PDFs have no semantic structure - only glyphs at coordinates. Headings must be
reconstructed, and the signal that survives most reliably is **font size
relative to the document's body text**.

The approach:

1. Extract text as spans with font size and position (`page.get_text("dict")`).
2. Compute the modal font size across the document. That is the body size, by
   definition - most characters in a document are body text.
3. A line whose dominant size exceeds body size by a threshold is a heading;
   its level is derived from how far above body it sits.
4. Consecutive same-size lines are joined into paragraphs; a vertical gap
   larger than a line height ends the paragraph.

Page numbers are recorded on every block, because a PDF citation that cannot
say "page 7" is barely a citation.

This is a heuristic and it will misread heavily designed documents. That is
acceptable: the alternative is a layout model, which is a different project.
What matters is that it degrades to "one paragraph per visual paragraph with
an empty heading path", which still retrieves - rather than to garbage.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from app.ingestion.blocks import Block, BlockType, ParsedDocument, assign_heading_paths
from app.ingestion.parsers.base import ParserError, derive_title

#: A line must be at least this many points larger than body text to count as
#: a heading. Below ~1.5pt the difference is usually just a bold run.
_HEADING_SIZE_DELTA = 1.5

#: Vertical gap (as a multiple of font size) that ends a paragraph.
_PARAGRAPH_GAP_RATIO = 1.6


class PdfParser:
    """Parses `.pdf` into blocks using font-size heading reconstruction."""

    extensions = (".pdf",)
    source_type = "pdf"

    def parse(self, path: Path) -> ParsedDocument:
        try:
            import pymupdf  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - optional extra
            raise ParserError(
                path, "PDF support needs the 'parsers' extra: pip install '.[parsers]'"
            ) from exc

        try:
            document = pymupdf.open(path)
        except Exception as exc:  # pymupdf raises bare Exception subclasses
            raise ParserError(path, f"could not be opened as a PDF: {exc}") from exc

        try:
            lines = self._extract_lines(document)
            body_size = self._modal_size(lines)
            blocks = self._lines_to_blocks(lines, body_size)
            page_count = document.page_count
            pdf_title = (document.metadata or {}).get("title") or None
        finally:
            document.close()

        assign_heading_paths(blocks)

        first_heading = next((b.text for b in blocks if b.is_heading), None)
        return ParsedDocument(
            title=derive_title(path, pdf_title or first_heading),
            blocks=blocks,
            source_type=self.source_type,
            source_uri=str(path),
            metadata={
                "page_count": page_count,
                "body_font_size": round(body_size, 2),
                "block_count": len(blocks),
            },
        )

    # -- extraction ---------------------------------------------------------
    def _extract_lines(self, document: Any) -> list[dict[str, Any]]:
        """Flatten the page dict into one record per visual line."""
        lines: list[dict[str, Any]] = []
        for page_index in range(document.page_count):
            page = document[page_index]
            data = page.get_text("dict")
            for block in data.get("blocks", []):
                if block.get("type") != 0:  # 0 = text, 1 = image
                    continue
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    text = "".join(s.get("text", "") for s in spans).strip()
                    if not text:
                        continue
                    # The dominant size is the one covering the most characters,
                    # so a single superscript does not reclassify the line.
                    size_weights: Counter[float] = Counter()
                    for span in spans:
                        size_weights[round(float(span.get("size", 0)), 1)] += len(
                            span.get("text", "")
                        )
                    dominant_size = size_weights.most_common(1)[0][0] if size_weights else 0.0
                    bbox = line.get("bbox", (0, 0, 0, 0))
                    lines.append(
                        {
                            "text": text,
                            "size": dominant_size,
                            "page": page_index + 1,
                            "top": float(bbox[1]),
                            "bottom": float(bbox[3]),
                            "char_count": len(text),
                        }
                    )
        return lines

    def _modal_size(self, lines: list[dict[str, Any]]) -> float:
        """Body font size = the size covering the most characters."""
        weights: Counter[float] = Counter()
        for line in lines:
            weights[line["size"]] += line["char_count"]
        if not weights:
            return 0.0
        return float(weights.most_common(1)[0][0])

    def _lines_to_blocks(
        self, lines: list[dict[str, Any]], body_size: float
    ) -> list[Block]:
        blocks: list[Block] = []
        buffer: list[dict[str, Any]] = []

        def flush() -> None:
            nonlocal buffer
            if not buffer:
                return
            text = " ".join(entry["text"] for entry in buffer).strip()
            if text:
                blocks.append(
                    Block(
                        type=BlockType.PARAGRAPH,
                        text=text,
                        page=buffer[0]["page"],
                        line_start=0,
                        line_end=0,
                    )
                )
            buffer = []

        previous: dict[str, Any] | None = None
        for line in lines:
            is_heading = body_size > 0 and line["size"] >= body_size + _HEADING_SIZE_DELTA

            if is_heading:
                flush()
                # Level from how far above body text the size sits: every
                # ~2.5pt step promotes one level, capped at 6.
                delta = line["size"] - body_size
                level = max(1, min(6, 4 - int(delta // 2.5)))
                blocks.append(
                    Block(
                        type=BlockType.HEADING,
                        text=line["text"],
                        level=level,
                        page=line["page"],
                    )
                )
                previous = line
                continue

            # A page change or a large vertical gap ends the paragraph.
            if previous is not None:
                gap = line["top"] - previous["bottom"]
                if line["page"] != previous["page"] or gap > line["size"] * _PARAGRAPH_GAP_RATIO:
                    flush()

            buffer.append(line)
            previous = line

        flush()
        return blocks
