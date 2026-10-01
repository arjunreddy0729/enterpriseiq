"""Ingest the demo corpus into PostgreSQL.

    python -m scripts.ingest_corpus                # incremental
    python -m scripts.ingest_corpus --force        # re-embed everything
    python -m scripts.ingest_corpus --dry-run      # parse and chunk, write nothing

Unchanged documents are skipped by content hash, so re-running this after
editing one file costs one embedding pass over one document.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import SessionLocal
from app.ingestion.chunking import ChunkingConfig, chunk_document
from app.ingestion.manifest import load_manifest, verify_files_exist
from app.ingestion.parsers import parse_file
from app.ingestion.pipeline import IngestionPipeline
from app.retrieval.embedder import BGEEmbedder

logger = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ingest_corpus")
    parser.add_argument("--corpus", type=Path, default=None, help="corpus directory")
    parser.add_argument("--force", action="store_true", help="re-embed unchanged documents")
    parser.add_argument("--dry-run", action="store_true", help="parse and chunk only")
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(level=settings.log_level, fmt=settings.log_format)
    corpus_dir = args.corpus or settings.corpus_dir

    if not corpus_dir.is_dir():
        print(f"error: corpus directory not found: {corpus_dir}", file=sys.stderr)
        return 2

    manifest = load_manifest(corpus_dir / "manifest.yaml")
    missing = verify_files_exist(manifest, corpus_dir)
    if missing:
        print("error: manifest references files that do not exist:", file=sys.stderr)
        for path in missing:
            print(f"  {path}", file=sys.stderr)
        return 2

    print(f"corpus:    {corpus_dir}")
    print(f"documents: {len(manifest.documents)}")
    print(f"model:     {settings.embedding_model} ({settings.embedding_dim}d)")

    if args.dry_run:
        config = ChunkingConfig.from_settings()
        total = 0
        for entry in manifest.documents:
            chunks = chunk_document(parse_file(corpus_dir / entry.path), config)
            total += len(chunks)
            print(f"  {entry.path:<55} {len(chunks):>3} chunks")
        print(f"\ndry run: {total} chunks, nothing written")
        return 0

    print("\nloading embedding model (first run downloads it) ...")
    embedder = BGEEmbedder()

    with SessionLocal() as session:
        pipeline = IngestionPipeline(session, embedder)
        report = pipeline.ingest_manifest(corpus_dir, force=args.force)

    print("\n" + "-" * 70)
    for outcome in report.outcomes:
        marker = {"ingested": "+", "updated": "~", "unchanged": "=", "failed": "!"}[outcome.status]
        detail = outcome.error or f"{outcome.chunks} chunks"
        print(f"  {marker} {outcome.path:<55} {detail}")
    print("-" * 70)

    summary = report.to_dict()
    print(
        f"  {summary['documents']} documents: "
        f"{summary['ingested']} new, {summary['updated']} updated, "
        f"{summary['unchanged']} unchanged, {summary['failed']} failed"
    )
    print(f"  {summary['chunks']} chunks in {summary['duration_ms']} ms")

    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
