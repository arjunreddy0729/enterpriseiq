"""Sync one source into the index.

    python -m scripts.sync_source local
    python -m scripts.sync_source github --repo owner/name --groups engineering
    python -m scripts.sync_source github --repo owner/name --groups engineering \
        --include docs/ --include README.md --token "$GITHUB_TOKEN"

Unchanged documents are skipped without being downloaded, and documents the
source no longer has are removed from the index. Both are what make this safe
to run on a schedule rather than by hand.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.ingestion.connectors import (
    Connector,
    ConnectorError,
    GitHubConnector,
    LocalFolderConnector,
)
from app.ingestion.pipeline import IngestionPipeline
from app.retrieval.embedder import BGEEmbedder

MARKERS = {
    "ingested": "+",
    "updated": "~",
    "unchanged": "=",
    "removed": "-",
    "failed": "!",
}


def build_connector(args: argparse.Namespace) -> Connector:
    if args.source == "local":
        corpus = args.corpus or get_settings().corpus_dir
        if not Path(corpus).is_dir():
            raise ConnectorError(f"corpus directory not found: {corpus}")
        return LocalFolderConnector(Path(corpus))

    # A token may come from the flag or the environment; the environment is
    # preferred in CI so it never lands in shell history or a process list.
    token = args.token or os.environ.get("GITHUB_TOKEN")
    return GitHubConnector(
        repo=args.repo,
        access_groups=args.groups,
        token=token,
        branch=args.branch,
        include=tuple(args.include),
        department=args.department,
        doc_type=args.doc_type,
        classification=args.classification,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sync_source")
    parser.add_argument("source", choices=["local", "github"])
    parser.add_argument("--force", action="store_true", help="re-embed even if unchanged")
    parser.add_argument(
        "--no-prune",
        action="store_true",
        help="keep documents the source no longer has (not recommended)",
    )
    parser.add_argument("--corpus", type=Path, default=None, help="local: corpus directory")
    parser.add_argument("--repo", help="github: owner/name")
    parser.add_argument(
        "--groups",
        action="append",
        default=[],
        help="github: group that may read this source (repeatable, required)",
    )
    parser.add_argument("--token", default=None, help="github: token (or set GITHUB_TOKEN)")
    parser.add_argument("--branch", default=None)
    parser.add_argument(
        "--include", action="append", default=[], help="github: path prefix (repeatable)"
    )
    parser.add_argument("--department", default=None)
    parser.add_argument("--doc-type", default="documentation", dest="doc_type")
    parser.add_argument("--classification", default="internal")
    args = parser.parse_args(argv)

    if args.source == "github":
        if not args.repo:
            parser.error("--repo is required for github")
        if not args.groups:
            parser.error(
                "--groups is required: GitHub grants read access per repository, "
                "so you must say which groups that maps to"
            )

    settings = get_settings()
    configure_logging(level=settings.log_level, fmt=settings.log_format)

    try:
        connector = build_connector(args)
    except ConnectorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"source:    {connector.name}")
    print(f"model:     {settings.embedding_model} ({settings.embedding_dim}d)")
    print("\nloading embedding model ...")
    embedder = BGEEmbedder()

    with SessionLocal() as session:
        pipeline = IngestionPipeline(session, embedder)
        try:
            report = pipeline.sync(connector, force=args.force, prune=not args.no_prune)
        except ConnectorError as exc:
            print(f"\nerror: {exc}", file=sys.stderr)
            return 2

    print("\n" + "-" * 72)
    for outcome in report.outcomes:
        detail = outcome.error or f"{outcome.chunks} chunks"
        print(f"  {MARKERS[outcome.status]} {outcome.path[:58]:<58} {detail}")
    print("-" * 72)

    summary = report.to_dict()
    print(
        f"  {summary['documents']} documents: {summary['ingested']} new, "
        f"{summary['updated']} updated, {summary['unchanged']} unchanged, "
        f"{summary['removed']} removed, {summary['failed']} failed"
    )
    print(f"  {summary['chunks']} chunks in {summary['duration_ms']} ms")
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
