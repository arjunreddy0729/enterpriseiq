"""The pre-generation relevance gate: decline before paying for a model call.

Every benchmark question is run through the real retrieval stack as the user
the benchmark says asks it, with a scripted stub model that records whether
it was called. Answerable questions must reach the model; questions that must
be declined (unanswerable, or about documents the asker cannot read) must
not. This costs nothing and pins the threshold to the data it was chosen
from: if a corpus or embedding change moves a question across the line, this
fails before the benchmark quietly gets worse.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.core.config import REPO_ROOT, get_settings
from app.core.identity import resolve_identity
from app.db.session import SessionLocal
from app.generation.llm import StubLLMClient
from app.retrieval.embedder import get_embedder
from app.services.query_service import QueryService
from tests.integration.conftest import requires_corpus

pytestmark = [pytest.mark.integration, requires_corpus]


def _cases() -> list[dict[str, Any]]:
    dataset = json.loads((REPO_ROOT / "evaluation" / "dataset.json").read_text())
    cases: list[dict[str, Any]] = dataset["cases"]
    # The case from the live demo that exposed the old, rank-based gate: an
    # engineer asking an HR-only question was sent to the model with three
    # unrelated on-call documents, because RRF scored them as highly as a
    # real answer.
    cases.append(
        {
            "id": "demo-engineer-asks-bonus-targets",
            "question": "What are the bonus targets by level?",
            "asked_by": "priya.raman@northwind.example",
            "must_abstain": True,
        }
    )
    return cases


CASES = _cases()


@pytest.fixture
def session() -> Iterator[Session]:
    with SessionLocal() as s:
        yield s


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_gate_calls_the_model_only_when_evidence_exists(
    session: Session, case: dict[str, Any]
) -> None:
    stub = StubLLMClient("Stub answer [1].")
    identity = resolve_identity(session, case["asked_by"])

    outcome = QueryService(session, get_embedder(), stub).answer(
        case["question"], identity, include_debug=True
    )

    if case["must_abstain"]:
        assert stub.calls == [], f"model was called: {outcome.debug}"
        assert outcome.status == "insufficient_evidence"
        assert outcome.abstained_before_model
    else:
        assert len(stub.calls) == 1, f"declined an answerable question: {outcome.debug}"


def test_a_gate_decline_explains_itself(session: Session) -> None:
    identity = resolve_identity(session, "priya.raman@northwind.example")
    outcome = QueryService(session, get_embedder(), StubLLMClient()).answer(
        "What are the bonus targets by level?", identity, include_debug=True
    )
    assert outcome.debug["abstention_reason"] == "no_relevant_candidates"
    assert outcome.debug["top_similarity"] < outcome.debug["min_similarity"]
    assert outcome.debug["min_similarity"] == get_settings().generation_min_similarity
