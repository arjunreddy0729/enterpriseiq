"""The benchmark runner.

Two modes, and the distinction matters more than it looks:

* **retrieval** - runs the retrieval stack only. Free, fast, and the mode you
  iterate in. Every retrieval change (chunk sizes, RRF k, the reranker, query
  rewriting) is measured here, and you can run it fifty times an afternoon
  without spending anything.
* **full** - adds generation. Costs money, so it runs when retrieval numbers
  are already where you want them.

Running the same fixed dataset before and after a change is what turns "the
reranker seems better" into a number you can put on a résumé and defend.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.identity import resolve_identity
from app.core.logging import get_logger
from app.evaluation import metrics
from app.evaluation.dataset import Category, EvalCase, EvalDataset
from app.generation.llm import LLMClient
from app.retrieval.embedder import get_embedder
from app.retrieval.pipeline import HybridRetrievalPipeline
from app.services.query_service import QueryService

logger = get_logger(__name__)

#: Cut-offs reported for every retrieval metric. 5 is what a reranker would
#: see; 10 is what the fused candidate set delivers.
CUTOFFS = (1, 3, 5, 10)


@dataclass(slots=True)
class CaseResult:
    case_id: str
    category: str
    question: str
    asked_by: str

    retrieved_documents: list[str] = field(default_factory=list)
    expected_sources: list[str] = field(default_factory=list)
    forbidden_sources: list[str] = field(default_factory=list)

    recall: dict[int, float] = field(default_factory=dict)
    precision: dict[int, float] = field(default_factory=dict)
    ndcg: dict[int, float] = field(default_factory=dict)
    reciprocal_rank: float = 0.0

    #: True when a forbidden document appeared in the results. Any non-zero
    #: count here is a security failure, not a quality metric.
    leaked: bool = False

    # Generation-only fields
    answered: bool | None = None
    abstained: bool | None = None
    abstention_correct: bool | None = None
    answer: str = ""
    cited_documents: list[str] = field(default_factory=list)
    citation_precision: float | None = None
    fact_coverage: float | None = None
    grounding_score: float | None = None
    confidence: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "category": self.category,
            "question": self.question,
            "asked_by": self.asked_by,
            "expected_sources": self.expected_sources,
            "retrieved_documents": self.retrieved_documents,
            "leaked": self.leaked,
            "recall": {str(k): round(v, 4) for k, v in self.recall.items()},
            "precision": {str(k): round(v, 4) for k, v in self.precision.items()},
            "ndcg": {str(k): round(v, 4) for k, v in self.ndcg.items()},
            "reciprocal_rank": round(self.reciprocal_rank, 4),
            "answered": self.answered,
            "abstained": self.abstained,
            "abstention_correct": self.abstention_correct,
            "answer": self.answer,
            "cited_documents": self.cited_documents,
            "citation_precision": self.citation_precision,
            "fact_coverage": self.fact_coverage,
            "grounding_score": self.grounding_score,
            "confidence": self.confidence,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "latency_ms": self.latency_ms,
        }


@dataclass(slots=True)
class RunReport:
    mode: str
    dataset_version: int
    results: list[CaseResult] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0

    # -- retrieval aggregates ------------------------------------------------
    def answerable(self) -> list[CaseResult]:
        """Cases with a correct document to find.

        Unanswerable and permission-negative cases are excluded from recall:
        there is nothing to retrieve, so including them would drag the average
        toward zero and make retrieval look worse the more honest the
        benchmark is.
        """
        return [r for r in self.results if r.expected_sources]

    def retrieval_summary(self) -> dict[str, Any]:
        scored = self.answerable()
        return {
            "cases": len(scored),
            "recall_at_k": {
                str(k): round(metrics.mean([r.recall.get(k, 0.0) for r in scored]), 4)
                for k in CUTOFFS
            },
            "precision_at_k": {
                str(k): round(metrics.mean([r.precision.get(k, 0.0) for r in scored]), 4)
                for k in CUTOFFS
            },
            "ndcg_at_k": {
                str(k): round(metrics.mean([r.ndcg.get(k, 0.0) for r in scored]), 4)
                for k in CUTOFFS
            },
            "mrr": round(metrics.mean([r.reciprocal_rank for r in scored]), 4),
        }

    def security_summary(self) -> dict[str, Any]:
        checked = [r for r in self.results if r.forbidden_sources]
        leaks = [r.case_id for r in checked if r.leaked]
        return {
            "cases_checked": len(checked),
            "leaks": len(leaks),
            "leaked_cases": leaks,
            "pass": not leaks,
        }

    def abstention_summary(self) -> dict[str, Any]:
        judged = [r for r in self.results if r.abstention_correct is not None]
        if not judged:
            return {}
        should = [r for r in judged if r.category in {"permission_negative", "unanswerable"}]
        should_not = [r for r in judged if r.category in {"factoid", "multi_hop"}]
        return {
            "accuracy": round(
                metrics.mean([1.0 if r.abstention_correct else 0.0 for r in judged]), 4
            ),
            "correctly_declined": sum(1 for r in should if r.abstained),
            "should_decline": len(should),
            "wrongly_declined": sum(1 for r in should_not if r.abstained),
            "should_answer": len(should_not),
        }

    def generation_summary(self) -> dict[str, Any]:
        answered = [r for r in self.results if r.answered]
        if not answered:
            return {}
        with_facts = [r for r in answered if r.fact_coverage is not None]
        return {
            "answered": len(answered),
            "fact_coverage": round(
                metrics.mean([r.fact_coverage or 0.0 for r in with_facts]), 4
            ),
            "citation_precision": round(
                metrics.mean([r.citation_precision or 0.0 for r in answered]), 4
            ),
            "grounding": round(
                metrics.mean([r.grounding_score or 0.0 for r in answered]), 4
            ),
            "confidence_bands": {
                band: sum(1 for r in answered if r.confidence == band)
                for band in ("high", "medium", "low")
            },
        }

    def system_summary(self) -> dict[str, Any]:
        latencies = [float(r.latency_ms) for r in self.results if r.latency_ms]
        return {
            "latency_ms": {
                "p50": round(metrics.percentile(latencies, 50)),
                "p95": round(metrics.percentile(latencies, 95)),
                "max": round(max(latencies)) if latencies else 0,
            },
            "input_tokens": sum(r.input_tokens for r in self.results),
            "output_tokens": sum(r.output_tokens for r in self.results),
            "total_cost_usd": round(sum(r.cost_usd for r in self.results), 4),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "dataset_version": self.dataset_version,
            "config": self.config,
            "duration_ms": self.duration_ms,
            "retrieval": self.retrieval_summary(),
            "security": self.security_summary(),
            "abstention": self.abstention_summary(),
            "generation": self.generation_summary(),
            "system": self.system_summary(),
            "cases": [r.to_dict() for r in self.results],
        }


class EvaluationRunner:
    def __init__(
        self,
        session: Session,
        llm: LLMClient | None = None,
        reranker: Any | None = None,
    ) -> None:
        self._session = session
        self._embedder = get_embedder()
        self._llm = llm
        self._reranker = reranker
        self._settings = get_settings()

    def run(self, dataset: EvalDataset, top_k: int = 10) -> RunReport:
        mode = "full" if self._llm is not None else "retrieval"
        started = time.perf_counter()
        settings = self._settings

        report = RunReport(
            mode=mode,
            dataset_version=dataset.version,
            config={
                "embedding_model": settings.embedding_model,
                "reranker_enabled": self._reranker is not None,
                "rrf_k": settings.rrf_k,
                "keyword_top_k": settings.retrieval_keyword_top_k,
                "vector_top_k": settings.retrieval_vector_top_k,
                "fusion_top_k": settings.retrieval_fusion_top_k,
                "chunk_target_tokens": settings.chunk_target_tokens,
                "chunk_max_tokens": settings.chunk_max_tokens,
                "eval_top_k": top_k,
                "llm_model": self._llm.model if self._llm else None,
            },
        )

        for case in dataset.cases:
            report.results.append(self._run_case(case, top_k))

        report.duration_ms = int((time.perf_counter() - started) * 1000)
        return report

    def _run_case(self, case: EvalCase, top_k: int) -> CaseResult:
        identity = resolve_identity(self._session, case.asked_by)
        result = CaseResult(
            case_id=case.id,
            category=case.category.value,
            question=case.question,
            asked_by=case.asked_by,
            expected_sources=list(case.expected_sources),
            forbidden_sources=list(case.forbidden_sources),
        )

        started = time.perf_counter()

        if self._llm is None:
            pipeline = HybridRetrievalPipeline(
                self._session, self._embedder, self._reranker
            )
            retrieval = pipeline.retrieve(
                text=case.question,
                allowed_group_ids=identity.group_ids,
                top_k=top_k,
            )
            candidates = retrieval.candidates
        else:
            service = QueryService(
                self._session, self._embedder, self._llm, self._reranker
            )
            outcome = service.answer(case.question, identity, top_k=top_k)
            candidates = outcome.candidates

            result.answered = outcome.answered
            result.abstained = not outcome.answered
            result.abstention_correct = result.abstained == case.must_abstain
            result.answer = outcome.answer
            result.cited_documents = _unique(
                c.source_uri for c in outcome.citations
            )
            result.confidence = outcome.confidence
            result.grounding_score = float(outcome.grounding.get("score", 0.0))
            result.input_tokens = int(outcome.usage.get("input_tokens") or 0)
            result.output_tokens = int(outcome.usage.get("output_tokens") or 0)
            result.cost_usd = float(outcome.usage.get("estimated_cost_usd") or 0.0)

            if outcome.answered:
                result.citation_precision = metrics.citation_precision(
                    result.cited_documents, case.expected_sources
                )
                if case.expected_facts:
                    result.fact_coverage = metrics.fact_coverage(
                        outcome.answer, case.expected_facts
                    )

        result.latency_ms = int((time.perf_counter() - started) * 1000)

        # Document-level retrieval scoring, preserving rank order.
        documents = _unique(c.source_uri for c in candidates)
        result.retrieved_documents = documents

        if case.expected_sources:
            for k in CUTOFFS:
                result.recall[k] = metrics.recall_at_k(documents, case.expected_sources, k)
                result.precision[k] = metrics.precision_at_k(
                    documents, case.expected_sources, k
                )
                result.ndcg[k] = metrics.ndcg_at_k(documents, case.expected_sources, k)
            result.reciprocal_rank = metrics.reciprocal_rank(
                documents, case.expected_sources
            )

        if case.forbidden_sources:
            leaked_docs = set(documents) & set(case.forbidden_sources)
            result.leaked = bool(leaked_docs)
            if leaked_docs:
                logger.error(
                    "evaluation_permission_leak",
                    case_id=case.id,
                    asked_by=case.asked_by,
                    leaked=sorted(leaked_docs),
                )

        return result


def _unique(values: Any) -> list[str]:
    """De-duplicate while preserving first-seen order.

    Several chunks of the same document collapse to one entry, so document-level
    metrics are not inflated by a system that returned four chunks of one file.
    """
    seen: dict[str, None] = {}
    for value in values:
        seen.setdefault(value, None)
    return list(seen)
