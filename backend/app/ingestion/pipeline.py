"""The ingestion pipeline: files on disk -> rows in PostgreSQL.

    manifest entry
        |
        v
    parse ---> blocks ---> chunk ---> embed ---> INSERT
        |                                          ^
        +-- content hash --------------------------+
            (unchanged? skip everything above)

Two decisions worth calling out.

**Content hashing.** Every document stores the SHA-256 of its normalised text.
Re-ingesting an unchanged corpus then costs one parse and zero embeddings,
which matters because you will re-run this constantly while tuning. It also
gives change detection for free: a differing hash is the signal to re-chunk
and re-embed exactly that document, not the whole corpus.

**ACL denormalisation.** `document_permissions` is the source of truth, but the
group ids are also written onto every chunk row. That is what lets the
retrieval-time access check be a single indexed predicate instead of a
three-table join executed after the vector scan. The cost is that changing a
document's permissions requires rewriting its chunks - handled here, in one
place, whenever a document is (re-)ingested.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core.identity import resolve_group_ids
from app.core.logging import get_logger
from app.db.models import Chunk, CorpusStat, Document, DocumentPermission
from app.ingestion.chunking import ChunkingConfig, chunk_document
from app.ingestion.connectors import Connector, LocalFolderConnector, SourceDocument
from app.ingestion.parsers import parse_file
from app.retrieval.ports import Embedder

logger = get_logger(__name__)


@dataclass(slots=True)
class DocumentOutcome:
    path: str
    status: str  # ingested | updated | unchanged | removed | failed
    document_id: str | None = None
    chunks: int = 0
    error: str | None = None


@dataclass(slots=True)
class IngestionReport:
    outcomes: list[DocumentOutcome] = field(default_factory=list)
    duration_ms: int = 0
    source: str = ""

    @property
    def ingested(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "ingested")

    @property
    def updated(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "updated")

    @property
    def unchanged(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "unchanged")

    @property
    def removed(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "removed")

    @property
    def failed(self) -> list[DocumentOutcome]:
        return [o for o in self.outcomes if o.status == "failed"]

    @property
    def total_chunks(self) -> int:
        return sum(o.chunks for o in self.outcomes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "documents": len(self.outcomes),
            "ingested": self.ingested,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "removed": self.removed,
            "failed": len(self.failed),
            "chunks": self.total_chunks,
            "duration_ms": self.duration_ms,
        }


def json_safe(value: Any) -> Any:
    """Convert a value into something JSONB will accept.

    YAML parses an unquoted `2024-07-01` into a `datetime.date`, which psycopg
    cannot adapt into a JSONB column - so one manifest entry with a date inside
    its free-form `metadata` block fails the whole document while its 21
    siblings succeed. Dates are the common case; sets and Paths are cheap to
    cover at the same time.
    """
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [json_safe(v) for v in value]
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return value


def content_hash(text: str) -> str:
    """SHA-256 over whitespace-normalised text.

    Normalising first means a reformatted file with identical content does not
    trigger a pointless re-embed of the whole document.
    """
    normalised = " ".join(text.split())
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


class IngestionPipeline:
    def __init__(
        self,
        session: Session,
        embedder: Embedder,
        config: ChunkingConfig | None = None,
    ) -> None:
        self._session = session
        self._embedder = embedder
        self._config = config or ChunkingConfig.from_settings()

    # -- entry points -------------------------------------------------------
    def ingest_manifest(self, corpus_dir: Path, *, force: bool = False) -> IngestionReport:
        """Sync the demo corpus. Kept as the name CI and the Space call."""
        return self.sync(LocalFolderConnector(corpus_dir), force=force)

    def sync(
        self, connector: Connector, *, force: bool = False, prune: bool = True
    ) -> IngestionReport:
        """Bring the index in line with one source.

        Three things happen, and the third is the one a folder-reading ingest
        never had to do:

        * documents the source has and we do not, or that changed, are ingested
        * documents whose revision matches what we stored are skipped without
          downloading, parsing or embedding them
        * documents the source no longer has are removed from the index

        That last step is why `prune` defaults on. A document deleted at the
        source but still retrievable here is the same failure as a permission
        leak - someone asks a question and gets an answer out of a file that
        was taken down.
        """
        started = time.perf_counter()
        report = IngestionReport(source=connector.name)
        seen: set[str] = set()

        for source_document in connector.fetch():
            seen.add(source_document.source_uri)
            try:
                outcome = self.ingest_document(source_document, connector.name, force=force)
                # Commit per document, not once at the end. A single bad
                # document otherwise takes every document ingested before it
                # down with the rollback - on a 400-document corpus that turns
                # one malformed file into a completely wasted run.
                self._session.commit()
            except Exception as exc:  # one bad document must not stop the run
                logger.exception("ingest_failed", path=source_document.source_uri)
                outcome = DocumentOutcome(
                    path=source_document.source_uri, status="failed", error=str(exc)
                )
                self._session.rollback()
            report.outcomes.append(outcome)

        if prune:
            report.outcomes.extend(self._prune(connector.name, seen))
            self._session.commit()

        self.refresh_corpus_stats()
        self._session.commit()
        report.duration_ms = int((time.perf_counter() - started) * 1000)
        logger.info("ingest_complete", **report.to_dict())
        return report

    def ingest_document(
        self, source_document: SourceDocument, source: str, *, force: bool = False
    ) -> DocumentOutcome:
        """Ingest one document, doing as little work as its revision allows."""
        existing = self._session.execute(
            select(Document).where(
                Document.source == source,
                Document.source_uri == source_document.source_uri,
                Document.status != "deleted",
            )
        ).scalar_one_or_none()

        # Cheapest exit: the source says it has not changed. No download, no
        # parse, no embedding. Permissions are still re-applied, because they
        # live outside the content and an ACL change must take effect without
        # a re-embed.
        if (
            existing is not None
            and not force
            and source_document.revision is not None
            and existing.revision == source_document.revision
        ):
            self._sync_permissions(existing, source_document)
            self._session.flush()
            return DocumentOutcome(
                path=source_document.source_uri,
                status="unchanged",
                document_id=str(existing.id),
                chunks=self._chunk_count(existing.id),
            )

        with source_document.materialise() as path:
            parsed = parse_file(path)
        digest = content_hash(parsed.text)

        # Second-cheapest exit: the revision moved but the text did not - a
        # reformat, a touched mtime, a rebased commit. Skip the embedding and
        # record the new revision so the next sync takes the cheap path.
        if existing is not None and existing.content_hash == digest and not force:
            existing.revision = source_document.revision
            self._sync_permissions(existing, source_document)
            self._session.flush()
            return DocumentOutcome(
                path=source_document.source_uri,
                status="unchanged",
                document_id=str(existing.id),
                chunks=self._chunk_count(existing.id),
            )

        document = existing or Document(source_uri=source_document.source_uri, source=source)
        is_update = existing is not None

        document.source = source
        document.title = source_document.title
        document.source_type = source_document.source_type
        document.content_hash = digest
        document.revision = source_document.revision
        document.department = source_document.department
        document.doc_type = source_document.doc_type
        document.owner = source_document.owner
        document.classification = source_document.classification
        document.status = "active"
        document.effective_date = source_document.effective_date
        document.source_updated_at = source_document.source_updated_at
        document.doc_metadata = json_safe(dict(source_document.metadata))
        if is_update:
            document.version = (document.version or 1) + 1

        self._session.add(document)
        self._session.flush()  # assigns document.id

        group_ids = self._sync_permissions(document, source_document)

        # Replace chunks wholesale rather than diffing. Chunk boundaries shift
        # when text changes, so there is no stable identity to diff against,
        # and a partial update would leave orphaned stale chunks in the index.
        self._session.execute(delete(Chunk).where(Chunk.document_id == document.id))

        chunks = chunk_document(parsed, self._config)
        if chunks:
            vectors = self._embedder.embed_documents([c.embed_text for c in chunks])
            for chunk, vector in zip(chunks, vectors, strict=True):
                self._session.add(
                    Chunk(
                        document_id=document.id,
                        chunk_index=chunk.index,
                        section_path=chunk.heading_trail or None,
                        page_from=chunk.page_from,
                        page_to=chunk.page_to,
                        content=chunk.text,
                        token_count=chunk.token_count,
                        embedding=vector.tolist(),
                        embedding_model=self._embedder.model_name,
                        access_group_ids=list(group_ids),
                        department=source_document.department,
                        doc_type=source_document.doc_type,
                        classification=source_document.classification,
                        source_updated_at=source_document.source_updated_at,
                    )
                )

        self._session.flush()
        logger.info(
            "document_ingested",
            path=source_document.source_uri,
            source=source,
            chunks=len(chunks),
            groups=source_document.access_groups,
            updated=is_update,
        )
        return DocumentOutcome(
            path=source_document.source_uri,
            status="updated" if is_update else "ingested",
            document_id=str(document.id),
            chunks=len(chunks),
        )

    def _prune(self, source: str, seen: set[str]) -> list[DocumentOutcome]:
        """Remove documents this source no longer has.

        The document row is kept with status='deleted' so the audit trail can
        still explain an answer that cited it, but its chunks are deleted
        outright: the moment a document is gone from the source it must stop
        being retrievable, and leaving the vectors behind with a soft-deleted
        parent would keep answering questions out of it.
        """
        stale = (
            self._session.execute(
                select(Document).where(Document.source == source, Document.status != "deleted")
            )
            .scalars()
            .all()
        )
        outcomes: list[DocumentOutcome] = []
        for document in stale:
            if document.source_uri in seen:
                continue
            self._session.execute(delete(Chunk).where(Chunk.document_id == document.id))
            document.status = "deleted"
            logger.info("document_removed", path=document.source_uri, source=source)
            outcomes.append(DocumentOutcome(path=document.source_uri, status="removed"))
        return outcomes

    # -- helpers ------------------------------------------------------------
    def _sync_permissions(self, document: Document, entry: SourceDocument) -> list[int]:
        """Make document_permissions match the manifest, then push to chunks."""
        group_ids = resolve_group_ids(self._session, entry.access_groups)

        self._session.execute(
            delete(DocumentPermission).where(DocumentPermission.document_id == document.id)
        )
        for group_id in group_ids:
            self._session.add(DocumentPermission(document_id=document.id, group_id=group_id))

        # Keep the denormalised copy on chunks in step. For an unchanged
        # document this is the only write, so an ACL edit is cheap.
        self._session.execute(
            update(Chunk)
            .where(Chunk.document_id == document.id)
            .values(access_group_ids=list(group_ids))
        )
        return group_ids

    def _chunk_count(self, document_id: Any) -> int:
        return int(
            self._session.execute(
                select(func.count()).select_from(Chunk).where(Chunk.document_id == document_id)
            ).scalar_one()
        )

    def refresh_corpus_stats(self) -> None:
        """Recompute N and average chunk length for the BM25 rescoring pass."""
        row = self._session.execute(
            select(func.count(Chunk.id), func.coalesce(func.avg(Chunk.token_count), 0.0))
        ).one()
        count, average = int(row[0]), float(row[1])

        stats = self._session.get(CorpusStat, 1)
        if stats is None:
            stats = CorpusStat(id=1)
            self._session.add(stats)
        stats.chunk_count = count
        stats.avg_chunk_length = average
        stats.updated_at = func.now()
        self._session.flush()
