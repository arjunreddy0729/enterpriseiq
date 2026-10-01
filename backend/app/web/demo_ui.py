"""What the public demo's web page does, without the page itself.

The Hugging Face Space renders a small Gradio UI (deploy/huggingface/app.py)
whose buttons call `ask` and `search` here. Keeping the logic in the backend
package, with no Gradio import, means it is linted, type-checked and tested
in CI like everything else; the Space file is layout only.

These functions call the services directly rather than going through HTTP,
so they apply the same protections the HTTP routes do, explicitly: the
caller's permissions (resolved from the persona's database groups, exactly as
a login would), the per-visitor rate limits, the relevance gate and the daily
spend cap (both inside QueryService), and the request log the audit reads.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from app.api.errors import BudgetExhaustedError, ConfigurationError
from app.api.routes.search import _log_search
from app.core.config import get_settings
from app.core.identity import Identity, resolve_identity
from app.core.rate_limit import address_from, limiter
from app.db.session import SessionLocal
from app.generation.llm import AnthropicClient, LLMClient
from app.retrieval.embedder import get_embedder
from app.retrieval.pipeline import HybridRetrievalPipeline
from app.retrieval.types import Candidate, Filters
from app.schemas.search import SearchRequest
from app.services.query_service import QueryOutcome, QueryService

#: Label shown in the UI -> seeded demo account.
PERSONAS: dict[str, str] = {
    "Marcus · HR": "marcus.webb@northwind.example",
    "Priya · Engineering": "priya.raman@northwind.example",
    "Dana · Finance": "dana.okafor@northwind.example",
    "Tom · Legal": "tom.lindqvist@northwind.example",
    "Sofia · Engineering + Finance": "sofia.reyes@northwind.example",
}

EXAMPLE_QUESTIONS: list[str] = [
    "What are the bonus targets by level?",
    "How do our services authenticate to each other?",
    "What is the meal expense cap when travelling?",
    "Do we have an office in Tokyo?",
]

_SNIPPET_CHARS = 420


@dataclass(frozen=True, slots=True)
class DemoResult:
    """Three Markdown panels: the answer, its sources, and how it got there."""

    answer: str
    sources: str
    trace: str


def client_key(headers: Mapping[str, str], peer: str | None) -> str:
    """The visitor's address, read exactly the way the HTTP rate limits read it."""
    return address_from(headers, peer, get_settings().forwarded_proxy_hops)


def ask(persona: str, question: str, visitor: str, *, llm: LLMClient | None = None) -> DemoResult:
    """Full pipeline: retrieve, gate, generate with Claude, verify."""
    problem = _validate(persona, question)
    if problem:
        return DemoResult(problem, "", "")
    settings = get_settings()
    if settings.rate_limits_active:
        wait = limiter.hit(f"ui-ask:{visitor}", settings.rate_limit_query_per_hour, 3600)
        if wait is not None:
            return DemoResult(
                f"⏳ You've reached the limit of {settings.rate_limit_query_per_hour} AI answers "
                f"per hour. Try again in {int(wait // 60) + 1} min, or use **Search only**, "
                "which is free and unlimited within reason.",
                "",
                "",
            )

    with SessionLocal() as session:
        identity = resolve_identity(session, PERSONAS[persona])
        try:
            service = QueryService(session, get_embedder(), llm or AnthropicClient())
            outcome = service.answer(question.strip(), identity, include_debug=True)
        except (BudgetExhaustedError, ConfigurationError) as exc:
            return DemoResult(f"⚠️ {exc.message}", "", _who(identity))
        service.log(f"ui-{uuid.uuid4()}", identity, question.strip(), Filters(), outcome)

    return DemoResult(_answer(outcome, identity), _sources(outcome), _trace(outcome, identity))


def search(persona: str, question: str, visitor: str) -> DemoResult:
    """Retrieval only. No model call, no cost."""
    problem = _validate(persona, question)
    if problem:
        return DemoResult(problem, "", "")
    settings = get_settings()
    if settings.rate_limits_active:
        wait = limiter.hit(f"ui-search:{visitor}", settings.rate_limit_search_per_minute, 60)
        if wait is not None:
            return DemoResult(f"⏳ Too many searches. Try again in {int(wait) + 1}s.", "", "")

    started = time.perf_counter()
    with SessionLocal() as session:
        identity = resolve_identity(session, PERSONAS[persona])
        result = HybridRetrievalPipeline(session, get_embedder()).retrieve(
            text=question.strip(), allowed_group_ids=identity.group_ids, top_k=5
        )
        took_ms = int((time.perf_counter() - started) * 1000)
        _log_search(
            session,
            f"ui-{uuid.uuid4()}",
            identity,
            SearchRequest(query=question.strip(), top_k=5),
            result,
            took_ms,
        )

    answer = (
        f"🔎 **{len(result.candidates)} passages** that {_first_name(persona)} is allowed to "
        "read, best match first. No AI model was called, so this cost nothing."
    )
    sources = "\n\n".join(_passage(i, c) for i, c in enumerate(result.candidates, start=1))
    trace = (
        f"{_who(identity)}\n\n"
        f"- Keyword search found **{result.keyword_count}** candidates and vector search "
        f"**{result.vector_count}**, both filtered to these groups *inside* the database query.\n"
        f"- Merged with reciprocal rank fusion, then the top 5 shown.\n"
        f"- Took {took_ms} ms."
    )
    return DemoResult(answer, sources or "_Nothing found._", trace)


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------
def _validate(persona: str, question: str) -> str | None:
    if persona not in PERSONAS:
        return "Pick who you are asking as."
    text = question.strip()
    if len(text) < 3:
        return "Type a question first."
    if len(text) > 500:
        return "Please keep questions under 500 characters."
    return None


def _first_name(persona: str) -> str:
    return persona.split(" ")[0]


def _who(identity: Identity) -> str:
    groups = ", ".join(g for g in identity.group_names)
    return f"**Asking as {identity.name}**, who can read documents shared with: `{groups}`."


def _answer(outcome: QueryOutcome, identity: Identity) -> str:
    if outcome.status == "answered":
        header = f"✅ **Answered** · confidence: **{(outcome.confidence or 'low').upper()}**"
        return f"{header}\n\n{outcome.answer}"
    return (
        f"🚫 **Declined.** {outcome.answer}\n\n"
        f"_{identity.name.split(' ')[0]} may simply not have access to the document that "
        "answers this. Try the same question as someone in another department._"
    )


def _sources(outcome: QueryOutcome) -> str:
    if not outcome.citations:
        return "_No sources: nothing was cited._"
    blocks = []
    for c in outcome.citations:
        section = f" · {c.section_path}" if c.section_path else ""
        snippet = _quote(c.snippet)
        blocks.append(
            f"**[{c.number}] {c.document_title}** · `{c.source_uri}`{section}"
            + (f"\n\n{snippet}" if snippet else "")
        )
    return "\n\n".join(blocks)


def _passage(rank: int, c: Candidate) -> str:
    section = f" · {c.section_path}" if c.section_path else ""
    return f"**{rank}. {c.document_title}** · `{c.source_uri}`{section}\n\n{_quote(c.content)}"


def _quote(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    if len(text) > _SNIPPET_CHARS:
        text = text[:_SNIPPET_CHARS].rsplit(" ", 1)[0] + " …"
    return "\n".join(f"> {line}" if line.strip() else ">" for line in text.splitlines())


def _trace(outcome: QueryOutcome, identity: Identity) -> str:
    debug = outcome.debug or {}
    retrieved = sorted({c.source_uri for c in outcome.candidates})
    lines = [
        _who(identity),
        "",
        f"- **Retrieved {len(outcome.candidates)} passages** from: "
        + (", ".join(f"`{u}`" for u in retrieved) if retrieved else "nothing")
        + ". Documents outside these groups were filtered out inside the database query.",
    ]
    if debug.get("abstention_reason") == "no_relevant_candidates":
        lines.append(
            f"- **Relevance gate:** best match similarity was "
            f"{debug.get('top_similarity', 0):.2f}, below the "
            f"{debug.get('min_similarity', 0):.2f} needed. Declined **without calling the "
            "model**, so this cost $0."
        )
    elif outcome.usage:
        cost = outcome.usage.get("estimated_cost_usd") or 0.0
        lines.append(
            f"- **Model called:** `{outcome.usage.get('model')}`, "
            f"{outcome.usage.get('input_tokens')} tokens in / "
            f"{outcome.usage.get('output_tokens')} out, about ${cost:.4f}."
        )
        if debug.get("abstention_reason") == "model_abstained":
            lines.append("- The model read the passages and said they don't answer this.")
    grounding = outcome.grounding or {}
    if outcome.status == "answered":
        lines.append(
            f"- **Citations checked:** every [n] maps to a real passage. "
            f"**Grounding:** {grounding.get('supported', 0)} of "
            f"{grounding.get('total_claims', 0)} sentences verified against their sources."
        )
    total = (outcome.timings_ms or {}).get("total_ms")
    if total is not None:
        lines.append(f"- Took {total} ms." if total < 1000 else f"- Took {total / 1000:.1f}s.")
    return "\n".join(lines)
