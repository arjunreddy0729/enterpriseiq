"""Parser registry.

One lookup table from file extension to parser. Adding a format is a one-line
registration; nothing downstream of the IR changes.

PDF and DOCX parsers are registered eagerly but import their heavy third-party
dependency lazily, inside `parse()`. That way a deployment without the
`parsers` extra still starts, still ingests Markdown and text, and produces a
clear actionable error only if someone actually hands it a PDF.
"""

from __future__ import annotations

from pathlib import Path

from app.ingestion.blocks import ParsedDocument
from app.ingestion.parsers.base import (
    Parser,
    ParserError,
    UnsupportedFormatError,
    derive_title,
)
from app.ingestion.parsers.docx import DocxParser
from app.ingestion.parsers.markdown import MarkdownParser
from app.ingestion.parsers.pdf import PdfParser
from app.ingestion.parsers.text import TextParser

__all__ = [
    "DocxParser",
    "MarkdownParser",
    "Parser",
    "ParserError",
    "ParsedDocument",
    "PdfParser",
    "TextParser",
    "UnsupportedFormatError",
    "derive_title",
    "get_parser",
    "parse_file",
    "supported_extensions",
]

_PARSERS: tuple[Parser, ...] = (
    MarkdownParser(),
    TextParser(),
    PdfParser(),
    DocxParser(),
)

_BY_EXTENSION: dict[str, Parser] = {
    extension: parser for parser in _PARSERS for extension in parser.extensions
}


def supported_extensions() -> tuple[str, ...]:
    return tuple(sorted(_BY_EXTENSION))


def get_parser(path: Path | str) -> Parser:
    """Return the parser registered for this file's extension."""
    path = Path(path)
    parser = _BY_EXTENSION.get(path.suffix.lower())
    if parser is None:
        raise UnsupportedFormatError(
            path,
            f"no parser for '{path.suffix}' (supported: {', '.join(supported_extensions())})",
        )
    return parser


def parse_file(path: Path | str) -> ParsedDocument:
    """Parse any supported file into the common IR."""
    path = Path(path)
    if not path.is_file():
        raise ParserError(path, "file does not exist")
    return get_parser(path).parse(path)
