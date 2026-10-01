"""Print how a document chunks, so boundaries can be judged before embedding.

    python -m scripts.show_chunks ../corpus/engineering/authentication.md
    python -m scripts.show_chunks ../corpus --corpus
    python -m scripts.show_chunks ../corpus/hr/benefits.md --full
    python -m scripts.show_chunks ../corpus --corpus --json > chunks.json

Chunking is the highest-leverage decision in the system and the one least
suited to being judged by a metric. A human reading twenty boundaries will spot
"this split a table in half" or "this chunk is three unrelated topics" in
seconds; no aggregate number surfaces either. So this tool exists before any
embedding code does, and the sizes it reports come from the same code path the
real pipeline uses.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from itertools import pairwise
from pathlib import Path

from app.core.config import get_settings
from app.ingestion.chunking import (
    Chunk,
    ChunkingConfig,
    ChunkingStats,
    chunk_document,
)
from app.ingestion.parsers import ParserError, parse_file, supported_extensions
from app.ingestion.tokens import get_token_counter

DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
RED = "\033[31m"


def _c(text: str, colour: str, enabled: bool) -> str:
    return f"{colour}{text}{RESET}" if enabled else text


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be 1 or greater")
    return number


def build_config(args: argparse.Namespace) -> ChunkingConfig:
    # `is None` for all three, not truthiness: `--overlap 0` is a meaningful
    # request (disable overlap) and must not be silently replaced by the
    # configured default.
    base = ChunkingConfig.from_settings()
    return ChunkingConfig(
        target_tokens=base.target_tokens if args.target is None else args.target,
        max_tokens=base.max_tokens if args.max is None else args.max,
        overlap_tokens=base.overlap_tokens if args.overlap is None else args.overlap,
        break_on_heading_level=args.break_level,
    )


def iter_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    extensions = set(supported_extensions())
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in extensions)


def preview(chunk: Chunk, width: int, lines: int) -> list[str]:
    body = chunk.text.strip().splitlines()
    shown = [line[:width] for line in body[:lines]]
    if len(body) > lines:
        shown.append(f"... (+{len(body) - lines} more lines)")
    return shown


def print_chunk(chunk: Chunk, cfg: ChunkingConfig, args: argparse.Namespace, colour: bool) -> None:
    over = chunk.token_count > cfg.max_tokens
    tag = _c(f"[{chunk.token_count:>4} tok]", RED if over else CYAN, colour)

    flags = []
    if chunk.has_overlap:
        flags.append("overlap")
    if chunk.is_split_block:
        flags.append("split-block")
    if over:
        flags.append("OVER MAX")
    flag_text = _c(f"  ({', '.join(flags)})", YELLOW, colour) if flags else ""

    trail = chunk.heading_trail or "(no heading)"
    location = f"L{chunk.line_start}-{chunk.line_end}"
    if chunk.page_from is not None:
        location = f"p{chunk.page_from}" + (
            f"-{chunk.page_to}" if chunk.page_to != chunk.page_from else ""
        )

    print(
        f"\n{_c(f'chunk {chunk.index:>3}', BOLD, colour)} {tag} {_c(location, DIM, colour)}{flag_text}"
    )
    print(f"  {_c(trail, DIM, colour)}")
    print(f"  {_c('blocks: ' + ', '.join(t.value for t in chunk.block_types), DIM, colour)}")

    if args.full:
        for line in chunk.text.splitlines():
            print(f"  | {line}")
    else:
        for line in preview(chunk, args.width, args.preview_lines):
            print(f"  | {line}")


def summarise(stats: ChunkingStats, cfg: ChunkingConfig, colour: bool) -> None:
    print(f"\n{_c('=' * 78, DIM, colour)}")
    print(_c("CORPUS SUMMARY", BOLD, colour))
    print(f"  documents      {stats.document_count}")
    print(f"  blocks         {stats.block_count}")
    print(f"  chunks         {stats.chunk_count}")
    if stats.document_count:
        print(f"  chunks/doc     {stats.chunk_count / stats.document_count:.1f}")
    print(
        f"  tokens         min {stats.min_tokens_seen} / "
        f"median {stats.median_tokens:.0f} / mean {stats.mean_tokens:.0f} / "
        f"max {stats.max_tokens_seen}"
    )
    print(f"  target/max     {cfg.target_tokens} / {cfg.max_tokens}")

    over = _c(str(stats.oversized), RED if stats.oversized else DIM, colour)
    print(f"  over max       {over}")
    print(f"  split blocks   {stats.split_blocks}")

    if stats.token_counts:
        buckets = [0, 100, 200, 300, 400, 500, 600, 700, 10_000]
        print(f"\n  {_c('token distribution', DIM, colour)}")
        for low, high in pairwise(buckets):
            count = sum(1 for t in stats.token_counts if low <= t < high)
            if not count:
                continue
            bar = "#" * max(1, round(40 * count / len(stats.token_counts)))
            label = f"{low}-{high if high < 10_000 else 'max'}"
            print(f"    {label:>9}  {bar} {count}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="show_chunks",
        description="Inspect how documents chunk before any embedding exists.",
    )
    parser.add_argument("path", type=Path, help="file or directory")
    parser.add_argument("--corpus", action="store_true", help="walk a directory and summarise")
    parser.add_argument("--full", action="store_true", help="print entire chunk text")
    parser.add_argument("--json", action="store_true", dest="as_json", help="emit JSON")
    parser.add_argument(
        "--exact", action="store_true", help="exact BGE token counts (needs the ml extra)"
    )
    parser.add_argument("--target", type=positive_int, default=None)
    parser.add_argument("--max", type=positive_int, default=None)
    parser.add_argument("--overlap", type=int, default=None)
    parser.add_argument("--break-level", type=int, default=2, dest="break_level")
    parser.add_argument("--preview-lines", type=int, default=3)
    parser.add_argument("--width", type=int, default=100)
    parser.add_argument("--no-color", action="store_true")
    args = parser.parse_args(argv)

    colour = sys.stdout.isatty() and not args.no_color
    cfg = build_config(args)

    counter = None
    if args.exact:
        try:
            counter = get_token_counter(get_settings().embedding_model)
        except RuntimeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

    if not args.path.exists():
        print(f"error: {args.path} does not exist", file=sys.stderr)
        return 2

    files = iter_files(args.path)
    if not files:
        print(f"error: no parseable files under {args.path}", file=sys.stderr)
        return 2

    stats = ChunkingStats()
    payload: list[dict[str, object]] = []
    failures: list[tuple[Path, str]] = []

    for file in files:
        try:
            document = parse_file(file)
        except ParserError as exc:
            failures.append((file, str(exc)))
            continue

        chunks = chunk_document(document, cfg, counter)
        stats.add(chunks, len(document.blocks), cfg.max_tokens)

        if args.as_json:
            payload.append(
                {
                    "path": str(file),
                    "title": document.title,
                    "source_type": document.source_type,
                    "blocks": len(document.blocks),
                    "chunks": [
                        {
                            "index": c.index,
                            "heading_path": list(c.heading_path),
                            "token_count": c.token_count,
                            "line_start": c.line_start,
                            "line_end": c.line_end,
                            "page_from": c.page_from,
                            "page_to": c.page_to,
                            "block_types": [t.value for t in c.block_types],
                            "has_overlap": c.has_overlap,
                            "is_split_block": c.is_split_block,
                            "text": c.text,
                            "embed_text": c.embed_text,
                        }
                        for c in chunks
                    ],
                }
            )
            continue

        header = f"{document.title}  {_c(f'({file})', DIM, colour)}"
        print(f"\n{_c('=' * 78, DIM, colour)}")
        print(_c(header, BOLD, colour))
        print(
            _c(
                f"{document.source_type} | {len(document.blocks)} blocks -> "
                f"{len(chunks)} chunks | counter: {(counter or get_token_counter()).name}",
                DIM,
                colour,
            )
        )
        if not args.corpus:
            for chunk in chunks:
                print_chunk(chunk, cfg, args, colour)

    if args.as_json:
        # asdict, not __dict__: ChunkingConfig uses slots and has no __dict__.
        print(json.dumps({"config": dataclasses.asdict(cfg), "documents": payload}, indent=2))
        return 0

    if len(files) > 1 or args.corpus:
        summarise(stats, cfg, colour)

    if failures:
        print(f"\n{_c('FAILED TO PARSE', RED, colour)}")
        for path, message in failures:
            print(f"  {path}: {message}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
