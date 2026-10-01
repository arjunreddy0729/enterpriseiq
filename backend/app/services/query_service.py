"""The query pipeline: question in, grounded answer out.

    retrieve  ->  abstain?  ->  build context  ->  generate  ->  abstain?
                                                                    |
              log  <-  confidence  <-  grounding  <-  resolve citations

There are two abstention points, and they catch different failures.

**Before the model runs.** If retrieval found nothing, or nothing that scores
above a floor, there is no evidence and no answer worth paying for. Skipping
the call here is the single most effective anti-hallucination measure in the
system, because "retrieval returned nothing relevant and the model answered
from memory" is the most common way a RAG system invents things - and it costs
nothing to prevent.

**After the model runs.** The passages looked plausible but did not actually
contain the answer, and the model said so via the sentinel. Cheaper to detect
than to prevent, and it is the case where the model is doing exactly what it
was asked to do.
"""

from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.errors import BudgetExhaustedError
from app.core.config import get_settings
from app.core.identity import Identity
from app.core.logging import get_logger
from app.db.models import QueryLog
from app.generation import confidence as confidence_module
from app.generation.citations import Citation, CitationResult, resolve
from app.generation.context import ContextBundle, build_context
from app.generation.grounding import GroundingReport, verify
from app.generation.llm import LLMClient
from app.generation.prompts import INSUFFICIENT_EVIDENCE, SYSTEM_PROMPT, build_user_prompt
from app.retrieval.filters import describe
from app.retrieval.pipeline import HybridRetrievalPipeline
from app.retrieval.ports import Embedder
from app.retrieval.types import Candidate, Filters, RetrievalQuery

logger = get_logger(__name__)

INSUFFICIENT_MESSAGE = (
    "I could not find enough information in the documents you have access to "
    "to answer this confidently."
)


@dataclass(slots=True)
class QueryOutcome:
    status: str  # answered | insufficient_evidence
    answer: str
    citations: list[Citation] = field(default_factory=list)
    confidence: str = "low"
    confidence_explanation: str = ""
    signals: dict[str, Any] = field(default_factory=dict)
    grounding: dict[str, Any] = field(default_factory=dict)
    candidates: list[Candidate] = field(default_factory=list)
    timings_ms: dict[str, int] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)
    debug: dict[str, Any] = field(default_factory=dict)
    abstained_before_model: bool = False

    @property
    def answered(self) -> bool:
        return self.status == "answered"


class QueryService:
    def __init__(
        self,
        session: Session,
        embedder: Embedder,
        llm: LLMClient,
        reranker: Any | None = None,
    ) -> None:
        self._session = session
        self._embedder = embedder
        self._llm = llm
        self._pipeline = HybridRetrievalPipeline(session, embedder, reranker)
        self._settings = get_settings()

    def answer(
        self,
        question: str,
        identity: Identity,
        filters: Filters | None = None,
        top_k: int | None = None,
        include_debug: bool = False,
    ) -> QueryOutcome:
        settings = self._settings
        filters = filters or Filters()
        started = time.perf_counter()
        timings: dict[str, int] = {}

        # --- retrieve ------------------------------------------------------
        retrieval = self._pipeline.retrieve(
            text=question,
            allowed_group_ids=identity.group_ids,
            filters=filters,
            top_k=top_k or settings.retrieval_rerank_top_k,
        )
        timings.update(retrieval.timings_ms)
        candidates = retrieval.candidates

        # --- abstain before spending a token -------------------------------
        # Gate on absolute similarity, not the fused score: RRF is rank-based,
        # so the top candidate scores about the same whether or not it is
        # relevant. See generation_min_similarity in config.
        top_similarity = max((c.vector_score or 0.0 for c in candidates), default=0.0)
        if top_similarity < settings.generation_min_similarity:
            return self._abstain(
                question,
                candidates,
                timings,
                started,
                reason="no_relevant_candidates",
                before_model=True,
                debug=(
                    {
                        "top_similarity": round(top_similarity, 4),
                        "min_similarity": settings.generation_min_similarity,
                    }
                    if include_debug
                    else {}
                ),
            )

        # --- assemble context ----------------------------------------------
        bundle: ContextBundle = build_context(candidates)
        if bundle.is_empty:
            return self._abstain(
                question,
                candidates,
                timings,
                started,
                reason="empty_context",
                before_model=True,
            )

        # --- spend cap ------------------------------------------------------
        # After both free abstention checks, so a question that would have
        # been declined anyway never counts against the budget.
        self._enforce_daily_budget()

        # --- generate --------------------------------------------------------
        generation_started = time.perf_counter()
        completion = self._llm.complete(
            system=SYSTEM_PROMPT,
            user=build_user_prompt(question, bundle.prompt_text),
        )
        timings["generate_ms"] = int((time.perf_counter() - generation_started) * 1000)

        usage = {
            "model": completion.model,
            "input_tokens": completion.input_tokens,
            "output_tokens": completion.output_tokens,
            "estimated_cost_usd": round(completion.estimated_cost_usd, 6),
        }

        if completion.was_refused:
            logger.warning("llm_refused", category=completion.refusal_category)
            outcome = self._abstain(question, candidates, timings, started, reason="model_refusal")
            outcome.usage = usage
            return outcome

        raw = completion.text.strip()

        # --- abstain after the model saw the evidence ----------------------
        if _is_abstention(raw):
            outcome = self._abstain(
                question, candidates, timings, started, reason="model_abstained"
            )
            outcome.usage = usage
            if include_debug:
                outcome.debug |= {"context": bundle.to_debug()}
            return outcome

        # --- validate citations ---------------------------------------------
        citation_result: CitationResult = resolve(raw, bundle)

        # --- verify grounding -------------------------------------------------
        verify_started = time.perf_counter()
        grounding: GroundingReport = verify(citation_result.answer, bundle, self._embedder)
        timings["verify_ms"] = int((time.perf_counter() - verify_started) * 1000)

        # --- confidence -------------------------------------------------------
        signals = confidence_module.compute_signals(candidates, citation_result, grounding)
        band = confidence_module.assess(signals)

        timings["total_ms"] = int((time.perf_counter() - started) * 1000)

        outcome = QueryOutcome(
            status="answered",
            answer=citation_result.answer,
            citations=citation_result.citations,
            confidence=band.value,
            confidence_explanation=confidence_module.explain(band, signals),
            signals=signals.to_dict(),
            grounding=grounding.to_dict(),
            candidates=candidates,
            timings_ms=timings,
            usage=usage,
        )
        if include_debug:
            outcome.debug = {
                **retrieval.to_debug(),
                "context": bundle.to_debug(),
                "invalid_citation_numbers": citation_result.invalid_numbers,
                "truncated": completion.was_truncated,
            }
        return outcome

    # -- helpers ------------------------------------------------------------
    def spent_today_usd(self) -> float:
        """Estimated model spend since 00:00 UTC, from query_logs."""
        today = dt.datetime.now(dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        spent = self._session.execute(
            select(func.coalesce(func.sum(QueryLog.estimated_cost_usd), 0)).where(
                QueryLog.created_at >= today
            )
        ).scalar_one()
        return float(spent or 0)

    def _enforce_daily_budget(self) -> None:
        """Refuse to call the model once today's estimated spend reaches the cap.

        Spend is read from the request log rather than kept in memory, so it
        survives restarts and is shared by every worker. Two limits of that:
        concurrent requests that pass the check together can overshoot by one
        answer each (cents, at max_tokens), and a request whose log write
        failed is not counted.
        """
        budget = self._settings.llm_daily_budget_usd
        if budget is None:
            return
        spent = self.spent_today_usd()
        if spent >= budget:
            logger.warning("daily_budget_exhausted", spent_usd=round(spent, 4), budget_usd=budget)
            raise BudgetExhaustedError(
                "The demo's daily budget for AI-written answers is used up. It resets at "
                "00:00 UTC. Search (/api/v1/search) still works and costs nothing.",
                details={"spent_usd": round(spent, 4), "budget_usd": budget},
            )

    def _abstain(
        self,
        question: str,
        candidates: list[Candidate],
        timings: dict[str, int],
        started: float,
        reason: str,
        before_model: bool = False,
        debug: dict[str, Any] | None = None,
    ) -> QueryOutcome:
        timings["total_ms"] = int((time.perf_counter() - started) * 1000)
        logger.info(
            "abstained",
            reason=reason,
            candidates=len(candidates),
            before_model=before_model,
        )
        return QueryOutcome(
            status="insufficient_evidence",
            answer=INSUFFICIENT_MESSAGE,
            confidence="low",
            confidence_explanation=(
                "No sufficiently relevant passages were found in the documents you have access to."
                if before_model
                else "The retrieved passages did not contain the answer."
            ),
            grounding={"score": 0.0, "supported": 0, "total_claims": 0, "passed": False},
            candidates=candidates,
            timings_ms=timings,
            debug={"abstention_reason": reason, **(debug or {})},
            abstained_before_model=before_model,
        )

    def log(
        self,
        request_id: str,
        identity: Identity,
        question: str,
        filters: Filters,
        outcome: QueryOutcome,
    ) -> None:
        """Persist the request. Best-effort - never fails the user's query."""
        try:
            self._session.add(
                QueryLog(
                    request_id=request_id or "unknown",
                    user_id=identity.user_id,
                    endpoint="query",
                    query=question,
                    filters=describe(
                        RetrievalQuery(
                            text=question,
                            allowed_group_ids=identity.group_ids,
                            filters=filters,
                        )
                    ),
                    candidates=[c.to_log_entry() for c in outcome.candidates],
                    used_chunk_ids=[c.chunk_id for c in outcome.citations],
                    # Everything retrieved, not only what was cited: an
                    # uncited passage still reached the model's context.
                    retrieved_document_ids=list(
                        dict.fromkeys(c.document_id for c in outcome.candidates)
                    ),
                    answer=outcome.answer,
                    citations=[
                        {
                            "number": c.number,
                            "chunk_id": str(c.chunk_id),
                            "source_uri": c.source_uri,
                        }
                        for c in outcome.citations
                    ],
                    grounding=outcome.grounding,
                    confidence=outcome.confidence,
                    llm_model=outcome.usage.get("model"),
                    prompt_tokens=outcome.usage.get("input_tokens"),
                    completion_tokens=outcome.usage.get("output_tokens"),
                    estimated_cost_usd=outcome.usage.get("estimated_cost_usd"),
                    latency_ms=outcome.timings_ms,
                    status=outcome.status,
                )
            )
            self._session.commit()
        except Exception:
            logger.warning("query_log_write_failed", exc_info=True)
            self._session.rollback()


def _is_abstention(text: str) -> bool:
    """Detect the sentinel.

    Checked as a bare token and as the whole message: a model that emits the
    sentinel plus a trailing period, or wraps it in a sentence, still meant to
    abstain, and treating that as a real answer would surface the sentinel to
    the user as if it were content.
    """
    stripped = text.strip().strip(".").strip()
    return stripped == INSUFFICIENT_EVIDENCE or (
        INSUFFICIENT_EVIDENCE in text and len(text) < len(INSUFFICIENT_EVIDENCE) + 80
    )
