"""Human-readable benchmark output."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.evaluation.runner import CUTOFFS, RunReport

BAR_WIDTH = 28


def _bar(value: float, width: int = BAR_WIDTH) -> str:
    filled = round(value * width)
    return "#" * filled + "." * (width - filled)


def render(report: RunReport) -> str:
    lines: list[str] = []
    add = lines.append

    add("=" * 74)
    add(f"  EnterpriseIQ benchmark - {report.mode} mode")
    add("=" * 74)

    config = report.config
    add(f"  embedding      {config.get('embedding_model')}")
    add(f"  reranker       {'enabled' if config.get('reranker_enabled') else 'disabled'}")
    add(
        f"  candidates     keyword {config.get('keyword_top_k')} + "
        f"vector {config.get('vector_top_k')} -> fused {config.get('fusion_top_k')} "
        f"-> eval top {config.get('eval_top_k')}"
    )
    add(f"  chunking       target {config.get('chunk_target_tokens')} / max {config.get('chunk_max_tokens')}")
    if config.get("llm_model"):
        add(f"  model          {config.get('llm_model')}")
    add("")

    # --- security ----------------------------------------------------------
    security = report.security_summary()
    verdict = "PASS" if security.get("pass") else "*** FAIL ***"
    add(f"  PERMISSION ENFORCEMENT                                   {verdict}")
    add(
        f"    {security.get('cases_checked', 0)} cases asked for a document the user "
        f"may not read"
    )
    add(f"    leaks: {security.get('leaks', 0)}")
    if security.get("leaked_cases"):
        for case_id in security["leaked_cases"]:
            add(f"      LEAKED: {case_id}")
    add("")

    # --- retrieval ---------------------------------------------------------
    retrieval = report.retrieval_summary()
    add(f"  RETRIEVAL  ({retrieval['cases']} answerable cases)")
    add(f"    {'k':>4}  {'recall':>8}  {'precision':>10}  {'nDCG':>8}")
    for k in CUTOFFS:
        add(
            f"    {k:>4}  {retrieval['recall_at_k'][str(k)]:>8.3f}  "
            f"{retrieval['precision_at_k'][str(k)]:>10.3f}  "
            f"{retrieval['ndcg_at_k'][str(k)]:>8.3f}"
        )
    add(f"    MRR   {retrieval['mrr']:.3f}   {_bar(retrieval['mrr'])}")
    add("")

    # --- abstention --------------------------------------------------------
    abstention = report.abstention_summary()
    if abstention:
        add("  ABSTENTION")
        add(
            f"    accuracy            {abstention['accuracy']:.3f}   "
            f"{_bar(abstention['accuracy'])}"
        )
        add(
            f"    correctly declined  {abstention['correctly_declined']}"
            f"/{abstention['should_decline']}"
        )
        add(
            f"    wrongly declined    {abstention['wrongly_declined']}"
            f"/{abstention['should_answer']}"
        )
        add("")

    # --- generation --------------------------------------------------------
    generation = report.generation_summary()
    if generation:
        add(f"  GENERATION  ({generation['answered']} answered)")
        add(
            f"    fact coverage       {generation['fact_coverage']:.3f}   "
            f"{_bar(generation['fact_coverage'])}"
        )
        add(
            f"    citation precision  {generation['citation_precision']:.3f}   "
            f"{_bar(generation['citation_precision'])}"
        )
        add(
            f"    grounding           {generation['grounding']:.3f}   "
            f"{_bar(generation['grounding'])}"
        )
        bands = generation["confidence_bands"]
        add(
            f"    confidence          high {bands['high']}  "
            f"medium {bands['medium']}  low {bands['low']}"
        )
        add("")

    # --- system ------------------------------------------------------------
    system = report.system_summary()
    add("  SYSTEM")
    add(
        f"    latency             p50 {system['latency_ms']['p50']}ms  "
        f"p95 {system['latency_ms']['p95']}ms  max {system['latency_ms']['max']}ms"
    )
    if system["input_tokens"]:
        add(
            f"    tokens              {system['input_tokens']} in / "
            f"{system['output_tokens']} out"
        )
        add(f"    estimated cost      ${system['total_cost_usd']:.4f}")
    add(f"    wall clock          {report.duration_ms / 1000:.1f}s")
    add("")

    # --- failures ----------------------------------------------------------
    failures = _failures(report)
    if failures:
        add(f"  CASES NEEDING ATTENTION ({len(failures)})")
        for line in failures:
            add(f"    {line}")
        add("")

    add("=" * 74)
    return "\n".join(lines)


def _failures(report: RunReport) -> list[str]:
    """Cases worth looking at by hand, with the reason."""
    out: list[str] = []
    for result in report.results:
        reasons = []
        if result.leaked:
            reasons.append("PERMISSION LEAK")
        if result.expected_sources and result.recall.get(5, 0.0) == 0.0:
            reasons.append("nothing relevant in top 5")
        if result.abstention_correct is False:
            reasons.append(
                "wrongly declined" if result.abstained else "answered when it should decline"
            )
        if result.fact_coverage is not None and result.fact_coverage < 1.0:
            reasons.append(f"facts {result.fact_coverage:.0%}")
        if reasons:
            out.append(f"{result.case_id:<12} {result.category:<20} {'; '.join(reasons)}")
    return out


def save(report: RunReport, directory: Path, label: str | None = None) -> Path:
    """Write the full report as JSON.

    Results are committed to the repository on purpose: a diff between two runs
    is the most direct way to see what a change did, and it makes any number
    quoted elsewhere traceable to the run that produced it.
    """
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    name = f"{stamp}-{report.mode}" + (f"-{label}" if label else "") + ".json"
    path = directory / name

    payload: dict[str, Any] = {"generated_at": datetime.now(UTC).isoformat(), **report.to_dict()}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path
