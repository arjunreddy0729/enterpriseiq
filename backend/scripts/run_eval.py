"""Run the benchmark.

    python -m scripts.run_eval                  # retrieval only - free
    python -m scripts.run_eval --full           # adds generation - costs money
    python -m scripts.run_eval --label baseline # tag the saved results file

Retrieval mode is the one to run constantly: it exercises the whole retrieval
stack, costs nothing, and is where every tuning decision should be measured.
Reach for --full when the retrieval numbers are already where you want them.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.evaluation.dataset import load_dataset, validate_against_corpus
from app.evaluation.report import render, save
from app.evaluation.runner import EvaluationRunner
from app.generation.llm import AnthropicClient
from app.ingestion.manifest import load_manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_eval")
    parser.add_argument("--dataset", type=Path, default=None)
    parser.add_argument("--results-dir", type=Path, default=None)
    parser.add_argument("--full", action="store_true", help="include generation (paid)")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--label", type=str, default=None)
    parser.add_argument("--no-save", action="store_true")
    parser.add_argument(
        "--rerank", action="store_true", help="enable the cross-encoder reranker"
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    # Quiet by default: per-request retrieval logs would bury the report.
    configure_logging(level="WARNING", fmt=settings.log_format)

    repo_root = settings.corpus_dir.parent
    dataset_path = args.dataset or repo_root / "evaluation" / "dataset.json"
    results_dir = args.results_dir or repo_root / "evaluation" / "results"

    if not dataset_path.is_file():
        print(f"error: dataset not found: {dataset_path}", file=sys.stderr)
        return 2

    dataset = load_dataset(dataset_path)

    # A question pointing at a document that no longer exists would silently
    # score zero recall forever, so fail loudly instead.
    manifest = load_manifest(settings.corpus_dir / "manifest.yaml")
    problems = validate_against_corpus(dataset, {d.path for d in manifest.documents})
    if problems:
        print("error: dataset references unknown documents:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 2

    print(f"dataset: {dataset_path.name}  ({len(dataset.cases)} cases)")
    print(f"         {dataset.counts}")

    llm = None
    if args.full:
        if not settings.llm_configured:
            print("error: --full needs ANTHROPIC_API_KEY in .env", file=sys.stderr)
            return 2
        llm = AnthropicClient()
        answerable = sum(1 for c in dataset.cases if not c.must_abstain)
        print(
            f"mode:    full (generation enabled, ~${0.02 * len(dataset.cases):.2f} "
            f"estimated, {answerable} answerable)"
        )
    else:
        print("mode:    retrieval only (free)")
    print()

    reranker = None
    if args.rerank:
        from app.retrieval.reranker import get_reranker

        reranker = get_reranker()
        print(f"rerank:  {reranker.model_name}")

    with SessionLocal() as session:
        runner = EvaluationRunner(session, llm=llm, reranker=reranker)
        report = runner.run(dataset, top_k=args.top_k)

    print(render(report))

    if not args.no_save:
        path = save(report, results_dir, args.label)
        print(f"  saved: {path.relative_to(repo_root)}")

    security = report.security_summary()
    if not security.get("pass"):
        print("\nFAILED: permission leak detected", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
