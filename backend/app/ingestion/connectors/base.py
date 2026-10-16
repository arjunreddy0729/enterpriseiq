"""What every source must provide.

A connector's job is not "give me files". It is to answer three questions for
each document, and the third is the one that makes this an enterprise problem
rather than a scraping problem:

    1. What is it?        title, type, metadata
    2. Has it changed?    a revision token, so unchanged documents cost nothing
    3. Who may read it?   access groups, mapped from the source's own ACLs

Most RAG connectors answer (1) and stop. That is how a system ends up with a
perfect index of documents it should never have shown anyone. Here
`access_groups` is a required field with no default, for the same reason
RetrievalQuery.allowed_group_ids has none: a source that has not decided who
may read its documents must fail loudly at the boundary, not quietly index
them as readable.

Content is fetched lazily. `fetch()` yields metadata and a revision; the
pipeline compares the revision against what it already has and only calls
`materialise()` for documents that actually changed. On a large source that is
the difference between a sync that costs one API listing and one that
re-downloads and re-embeds everything.
"""

from __future__ import annotations

import datetime as dt
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

#: source_type -> the suffix a parser dispatches on.
_SUFFIX = {
    "markdown": ".md",
    "txt": ".txt",
    "pdf": ".pdf",
    "docx": ".docx",
}


class ConnectorError(RuntimeError):
    """A source could not be reached or understood."""


@dataclass(slots=True)
class SourceDocument:
    """One document as a source describes it, before anything is fetched."""

    #: Stable and unique within the source. Changing it for the same document
    #: makes the old one look deleted and the new one look new.
    source_uri: str
    title: str
    source_type: str
    #: Group NAMES, resolved to ids during ingestion so an unknown name fails
    #: loudly rather than silently making a document readable by nobody.
    access_groups: list[str]

    #: Exactly one of these supplies the bytes.
    local_path: Path | None = None
    loader: Callable[[], bytes] | None = None

    #: The source's own change token: a git blob SHA, an ETag, an mtime.
    #: None means "cannot tell", and the pipeline falls back to hashing the
    #: parsed text, which is correct but costs a download and a parse.
    revision: str | None = None

    department: str | None = None
    doc_type: str | None = None
    owner: str | None = None
    classification: str = "internal"
    effective_date: dt.date | None = None
    source_updated_at: dt.datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.access_groups:
            raise ConnectorError(
                f"{self.source_uri}: no access_groups. A document whose audience is "
                "unknown must not be indexed - decide who may read it at the source."
            )
        if self.local_path is None and self.loader is None:
            raise ConnectorError(f"{self.source_uri}: needs either local_path or loader")

    @property
    def suffix(self) -> str:
        return _SUFFIX.get(self.source_type, Path(self.source_uri).suffix or ".txt")

    @contextmanager
    def materialise(self) -> Iterator[Path]:
        """Yield a filesystem path the parsers can read.

        Local sources hand over the real file. Remote sources are written to a
        temporary file with the right suffix, because parser dispatch is by
        extension and a PDF parsed as text is silently garbage rather than an
        error.
        """
        if self.local_path is not None:
            yield self.local_path
            return

        assert self.loader is not None  # guaranteed by __post_init__
        data = self.loader()
        # delete=False and an explicit unlink, because the parser opens the
        # path by name while this handle is still around and Windows will not
        # allow that otherwise.
        with tempfile.NamedTemporaryFile(suffix=self.suffix, delete=False) as handle:
            handle.write(data)
            temp_path = Path(handle.name)
        try:
            yield temp_path
        finally:
            temp_path.unlink(missing_ok=True)


@runtime_checkable
class Connector(Protocol):
    """A source of documents."""

    @property
    def name(self) -> str:
        """Stable identifier, stored on every document it produces.

        It scopes the deletion sweep, so it must not change between syncs of
        the same source or every document will look new and every old one
        deleted.
        """
        ...

    def fetch(self) -> Iterator[SourceDocument]: ...
