"""A folder on disk, described by a manifest.

This is the demo corpus, and it is also the proof that the connector contract
fits something that already worked. The manifest declares each document's
access groups explicitly, which is what a real source's ACL API would
otherwise tell us.

Revision is the file's mtime and size rather than a content hash: the point of
a revision token is to be cheaper than reading the file, and stat() is.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from app.ingestion.connectors.base import Connector, ConnectorError, SourceDocument
from app.ingestion.manifest import load_manifest


class LocalFolderConnector(Connector):
    """Documents from a directory containing a manifest.yaml."""

    def __init__(self, corpus_dir: Path, name: str = "local-corpus") -> None:
        self._dir = Path(corpus_dir)
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def fetch(self) -> Iterator[SourceDocument]:
        manifest_path = self._dir / "manifest.yaml"
        if not manifest_path.is_file():
            raise ConnectorError(f"no manifest.yaml in {self._dir}")

        manifest = load_manifest(manifest_path)
        for entry in manifest.documents:
            path = self._dir / entry.path
            if not path.is_file():
                raise ConnectorError(f"manifest lists {entry.path}, which does not exist")

            stat = path.stat()
            yield SourceDocument(
                source_uri=entry.path,
                title=entry.title,
                source_type=entry.source_type,
                access_groups=list(entry.access_groups),
                local_path=path,
                revision=f"{stat.st_mtime_ns}:{stat.st_size}",
                department=entry.department,
                doc_type=entry.doc_type,
                owner=entry.owner,
                classification=entry.classification,
                effective_date=entry.effective_date,
                source_updated_at=entry.source_updated_at,
                metadata=dict(entry.metadata),
            )
