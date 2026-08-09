"""The query pipeline end to end, with a scripted model.

Uses StubLLMClient so these run against the real database, the real retrieval
stack and the real citation/grounding code, but cost nothing and never vary.
Anything asserting what Claude actually says belongs in the evaluation
harness, not in a unit test.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.core.identity import resolve_identity
from app.db.session import SessionLocal
from app.generation.llm import StubLLMClient
from app.generation.prompts import INSUFFICIENT_EVIDENCE
from app.retrieval.embedder import get_embedder
from app.services.query_service import QueryService
from tests.integration.conftest import requires_corpus

pytestmark = [pytest.mark.integration, requires_corpus]

ENGINEER = "priya.raman@northwind.example"
HR_PERSON = "marcus.webb@northwind.example"


@pytest.fixture
def session() -> Session:
    with SessionLocal() as s:
        yield s


def service(session: Session, response: str) -> QueryService:
    return QueryService(session, get_embedder(), StubLLMClient(response))


def ask(session: Session, email: str, question: str, response: str):
    identity = resolve_identity(session, email)
    return service(session, response).answer(question, identity, include_debug=True)


# ---------------------------------------------------------------------------
# Abstention
# ---------------------------------------------------------------------------
def test_model_abstention_sentinel_is_honoured(session: Session) -> None:
    outcome = ask(session, ENGINEER, "How does authentication work?", INSUFFICIENT_EVIDENCE)
    assert outcome.status == "insufficient_evidence"
    assert "could not find enough information" in outcome.answer
    assert outcome.confidence == "low"


def test_sentinel_wrapped_in_punctuation_still_abstains(session: Session) -> None:
    outcome = ask(session, ENGINEER, "How does auth work?", f"{INSUFFICIENT_EVIDENCE}.")
    assert outcome.status == "insufficient_evidence"


def test_sentinel_never_leaks_into_a_user_facing_answer(session: Session) -> None:
    outcome = ask(session, ENGINEER, "How does auth work?", INSUFFICIENT_EVIDENCE)
    assert INSUFFICIENT_EVIDENCE not in outcome.answer


def test_a_user_with_no_access_abstains_without_calling_the_model(
    session: Session,
) -> None:
    """The cheapest anti-hallucination measure: no evidence, no API call."""
    stub = StubLLMClient("This should never be generated.")
    identity = resolve_identity(session, ENGINEER)
    # Force zero retrievable chunks by emptying the caller's groups.
    stripped = identity.__class__(
        user_id=identity.user_id,
        email=identity.email,
        name=identity.name,
        role=identity.role,
        group_ids=(),
        group_names=(),
    )
    outcome = QueryService(session, get_embedder(), stub).answer("anything at all", stripped)

    assert outcome.status == "insufficient_evidence"
    assert outcome.abstained_before_model
    assert stub.calls == [], "the model must not be called when there is no evidence"


# ---------------------------------------------------------------------------
# Citations
# ---------------------------------------------------------------------------
def test_answer_citations_resolve_to_real_documents(session: Session) -> None:
    outcome = ask(
        session, ENGINEER, "How does service authentication work?",
        "Services authenticate with OAuth 2.0 client credentials [1].",
    )
    assert outcome.status == "answered"
    assert outcome.citations
    citation = outcome.citations[0]
    assert citation.source_uri.endswith(".md")
    assert citation.snippet


def test_fabricated_citation_is_dropped_end_to_end(session: Session) -> None:
    outcome = ask(
        session, ENGINEER, "How does authentication work?",
        "A real claim [1]. A claim citing a passage that was never supplied [99].",
    )
    assert "[99]" not in outcome.answer
    assert all(c.number != 99 for c in outcome.citations)


def test_only_permitted_documents_can_be_cited(session: Session) -> None:
    """The strongest form of the permission guarantee: even when the model is
    scripted to cite everything, no restricted document can appear, because no
    restricted passage ever entered the context."""
    outcome = ask(
        session, ENGINEER, "What are the compensation bands and bonus targets?",
        "Claim [1][2][3][4][5][6].",
    )
    for citation in outcome.citations:
        assert citation.source_uri != "hr/compensation-policy.md"
        assert citation.source_uri != "hr/performance-review-process.md"


def test_hr_user_can_cite_the_hr_document(session: Session) -> None:
    outcome = ask(
        session, HR_PERSON, "What are the bonus targets by level?", "Claim [1][2][3]."
    )
    uris = {c.source_uri for c in outcome.citations}
    assert "hr/compensation-policy.md" in uris


# ---------------------------------------------------------------------------
# Grounding and confidence
# ---------------------------------------------------------------------------
def test_invented_content_scores_badly_on_grounding(session: Session) -> None:
    outcome = ask(
        session, ENGINEER, "How does authentication work?",
        "Northwind authenticates using biometric retina scanning at every office turnstile [1].",
    )
    assert outcome.grounding["score"] < 0.5
    assert outcome.confidence in {"low", "medium"}


def test_an_answer_citing_nothing_is_low_confidence(session: Session) -> None:
    outcome = ask(
        session, ENGINEER, "How does authentication work?",
        "Services authenticate somehow, and it is generally quite secure overall.",
    )
    assert outcome.confidence == "low"
    assert outcome.citations == []


def test_usage_and_timings_are_recorded(session: Session) -> None:
    outcome = ask(session, ENGINEER, "How does authentication work?", "Answer [1].")
    assert outcome.usage["model"] == "stub-model"
    assert "generate_ms" in outcome.timings_ms
    assert "total_ms" in outcome.timings_ms


def test_restricted_text_never_reaches_the_prompt(session: Session) -> None:
    """Inspect what was actually sent to the model, not just what came back."""
    stub = StubLLMClient("Answer [1].")
    identity = resolve_identity(session, ENGINEER)
    QueryService(session, get_embedder(), stub).answer(
        "compensation bands bonus target equity refresh", identity
    )
    assert stub.calls, "expected the model to be called"
    _system, user_prompt = stub.calls[0]

    # Match the "Source:" header a passage block carries, not a bare filename.
    # Documents legitimately cross-reference each other by name - remote-work-
    # policy.md (readable by everyone) mentions compensation-policy.md in its
    # prose - so a substring check on the filename alone reports a leak that
    # did not happen.
    for restricted in ("hr/compensation-policy.md", "hr/performance-review-process.md"):
        assert f"Source: {restricted}" not in user_prompt
