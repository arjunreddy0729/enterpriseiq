"""The parser contract.

Every source format reduces to the same thing: an ordered list of Blocks. That
uniformity is what lets one chunker serve PDFs, Markdown, plain text and Word
documents without a single format-specific branch.

Adding a connector later (Confluence, Notion, a GitHub repo walk) means writing
one class that satisfies this Protocol. Nothing downstream changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from app.ingestion.blocks import ParsedDocument


class ParserError(RuntimeError):
    """Raised when a file cannot be parsed.

    Carries the path so a failure inside a bulk ingest names the offender
    instead of producing an anonymous traceback.
    """

    def __init__(self, path: Path | str, message: str) -> None:
        self.path = Path(path)
        super().__init__(f"{self.path}: {message}")


class UnsupportedFormatError(ParserError):
    """No parser is registered for this file extension."""


@runtime_checkable
class Parser(Protocol):
    """Turns one file into a ParsedDocument."""

    #: File extensions this parser claims, lowercase and dot-prefixed.
    extensions: tuple[str, ...]

    #: The value written to documents.source_type.
    source_type: str

    def parse(self, path: Path) -> ParsedDocument: ...


def derive_title(path: Path, first_heading: str | None) -> str:
    """Pick a human title for a document.

    The first H1 wins when there is one; otherwise the filename, de-slugified.
    `adr-0007-postgres-partitioning.md` -> `Adr 0007 Postgres Partitioning`.
    The manifest can override this - it is a fallback, not the final word.
    """
    if first_heading:
        return first_heading.strip()
    stem = path.stem.replace("-", " ").replace("_", " ").strip()
    return stem.title() if stem else path.name
