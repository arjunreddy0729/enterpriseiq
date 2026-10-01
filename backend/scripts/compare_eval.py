"""Diff two benchmark runs.

    python -m scripts.compare_eval baseline.json reranked.json

Exists so "did that change help?" is answered by subtraction rather than by
looking at two reports side by side and forming an impression. A change that
does not move a number is a finding, not a failure - but it has to be visible
to be reported honestly.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _delta(before: float, after: float) -> str:
    change = after - before
    if abs(change) < 5e-4:
        return "     ="
    return f"{change:+.3f}"


def _row(label: str, before: float, after: float, width: int = 22) -> str:
    return f"    {label:<{width}} {before:>7.3f}  ->  {after:>7.3f}   {_delta(before, after)}"


def compare(before: dict[str, Any], after: dict[str, Any]) -> str:
    lines: list[str] = []
    add = lines.append

    add("=" * 74)
    add("  BENCHMARK COMPARISON")
    add("=" * 74)
    add(
        f"  before : {(before['config'].get('reranker_enabled') and 'reranked') or 'baseline'}  ({before['mode']} mode)"
    )
    add(
        f"  after  : {(after['config'].get('reranker_enabled') and 'reranked') or 'baseline'}  ({after['mode']} mode)"
    )
    add("")

    br, ar = before["retrieval"], after["retrieval"]
    add("  RETRIEVAL")
    for k in ("1", "3", "5", "10"):
        add(_row(f"recall@{k}", br["recall_at_k"][k], ar["recall_at_k"][k]))
    for k in ("1", "3", "5", "10"):
        add(_row(f"nDCG@{k}", br["ndcg_at_k"][k], ar["ndcg_at_k"][k]))
    add(_row("MRR", br["mrr"], ar["mrr"]))
    add("")

    if before.get("generation") and after.get("generation"):
        bg, ag = before["generation"], after["generation"]
        add("  GENERATION")
        for key in ("fact_coverage", "citation_precision", "grounding"):
            if key in bg and key in ag:
                add(_row(key, bg[key], ag[key]))
        add("")

    if before.get("abstention") and after.get("abstention"):
        add("  ABSTENTION")
        add(_row("accuracy", before["abstention"]["accuracy"], after["abstention"]["accuracy"]))
        add("")

    bs, as_ = before["system"], after["system"]
    add("  COST OF THE CHANGE")
    add(_row("latency p50 (ms)", bs["latency_ms"]["p50"], as_["latency_ms"]["p50"], 22))
    add(_row("latency p95 (ms)", bs["latency_ms"]["p95"], as_["latency_ms"]["p95"], 22))
    if bs.get("total_cost_usd") or as_.get("total_cost_usd"):
        add(_row("cost ($)", bs["total_cost_usd"], as_["total_cost_usd"]))
    add("")

    # Per-case document-order churn: a change can reshuffle results without
    # moving any aggregate, and that is worth seeing.
    b_cases = {c["case_id"]: c for c in before["cases"]}
    a_cases = {c["case_id"]: c for c in after["cases"]}
    shared = sorted(set(b_cases) & set(a_cases))
    reordered = [
        cid
        for cid in shared
        if b_cases[cid]["retrieved_documents"] != a_cases[cid]["retrieved_documents"]
    ]
    improved = [
        cid for cid in shared if a_cases[cid]["reciprocal_rank"] > b_cases[cid]["reciprocal_rank"]
    ]
    regressed = [
        cid for cid in shared if a_cases[cid]["reciprocal_rank"] < b_cases[cid]["reciprocal_rank"]
    ]

    add("  PER-CASE")
    add(f"    document order changed  {len(reordered)}/{len(shared)}")
    add(f"    rank improved           {len(improved)}  {improved[:6]}")
    add(f"    rank regressed          {len(regressed)}  {regressed[:6]}")
    add("")
    add("=" * 74)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="compare_eval")
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    args = parser.parse_args(argv)

    print(
        compare(
            json.loads(args.before.read_text(encoding="utf-8")),
            json.loads(args.after.read_text(encoding="utf-8")),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
