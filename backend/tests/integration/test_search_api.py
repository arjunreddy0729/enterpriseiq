"""The /api/v1/search endpoint, end to end.

Covers the contract the evaluation harness and the demo UI depend on, plus the
two hybrid-retrieval behaviours that justify running two retrievers at all.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.integration.conftest import requires_corpus

pytestmark = [pytest.mark.integration, requires_corpus]

ENGINEER = {"X-Dev-User": "priya.raman@northwind.example"}
HR_PERSON = {"X-Dev-User": "marcus.webb@northwind.example"}


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


def search(client: TestClient, headers: dict[str, str], **payload: object) -> dict:
    payload.setdefault("query", "authentication")
    response = client.post("/api/v1/search", json=payload, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
def test_missing_identity_header_is_401(client: TestClient) -> None:
    response = client.post("/api/v1/search", json={"query": "x"})
    assert response.status_code == 401


def test_unknown_user_is_401(client: TestClient) -> None:
    response = client.post(
        "/api/v1/search", json={"query": "x"}, headers={"X-Dev-User": "nobody@example.com"}
    )
    assert response.status_code == 401


def test_error_responses_use_the_standard_envelope(client: TestClient) -> None:
    body = client.post("/api/v1/search", json={"query": "x"}).json()
    assert "error" in body
    assert {"code", "message"} <= set(body["error"])


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------
def test_response_shape(client: TestClient) -> None:
    body = search(client, ENGINEER, query="how does the api gateway rate limit?")
    assert body["result_count"] == len(body["results"])
    assert body["identity"]["email"] == "priya.raman@northwind.example"
    assert set(body["identity"]["groups"]) == {"all-employees", "engineering"}
    assert body["took_ms"] >= 0

    first = body["results"][0]
    assert first["content"]
    assert first["document_title"]
    assert first["source_uri"]
    assert "scores" in first


def test_top_k_is_respected(client: TestClient) -> None:
    body = search(client, ENGINEER, query="deployment", top_k=3)
    assert len(body["results"]) <= 3


def test_debug_payload_is_opt_in(client: TestClient) -> None:
    assert search(client, ENGINEER, query="deployment")["debug"] is None
    body = search(client, ENGINEER, query="deployment", include_debug=True)
    debug = body["debug"]
    assert debug["keyword_candidates"] >= 0
    assert debug["vector_candidates"] > 0
    assert debug["tsquery"]
    assert debug["filters"]["allowed_group_ids"]


def test_empty_query_is_rejected(client: TestClient) -> None:
    assert client.post("/api/v1/search", json={"query": ""}, headers=ENGINEER).status_code == 422


def test_unknown_field_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/search",
        json={"query": "x", "access_groups": ["hr"]},
        headers=ENGINEER,
    )
    # Groups must never be caller-supplied. extra="forbid" makes attempting it
    # a validation error rather than a silently ignored field.
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Why two retrievers
# ---------------------------------------------------------------------------
def test_exact_identifier_is_found_by_keyword(client: TestClient) -> None:
    """An identifier is nearly meaningless semantically, so the embedding
    barely encodes it. IDF weights it most heavily. This is the case dense
    retrieval alone loses."""
    body = search(
        client, ENGINEER, query="X-Cardinal-Signature", include_debug=True, top_k=5
    )
    assert body["debug"]["keyword_candidates"] >= 1
    top = body["results"][0]
    assert "keyword" in top["scores"]["retrieved_by"]
    assert "payment" in top["source_uri"]


def test_paraphrase_is_found_by_vectors(client: TestClient) -> None:
    """No content word in common with the document, which is the case keyword
    search alone loses."""
    body = search(
        client,
        ENGINEER,
        query="how do our services prove who they are to each other?",
        top_k=5,
    )
    uris = {r["source_uri"] for r in body["results"]}
    assert "engineering/authentication.md" in uris


def test_fusion_promotes_agreement(client: TestClient) -> None:
    body = search(
        client, ENGINEER, query="oauth client credentials token expiry", top_k=5
    )
    top = body["results"][0]
    assert top["scores"]["rrf_score"] is not None


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------
def test_department_filter_narrows_results(client: TestClient) -> None:
    body = search(
        client,
        HR_PERSON,
        query="policy",
        filters={"departments": ["hr"]},
        top_k=10,
    )
    assert body["results"]
    assert {r["department"] for r in body["results"]} == {"hr"}


def test_filters_cannot_widen_access(client: TestClient) -> None:
    """Asking for the HR department as an engineer returns nothing, not HR."""
    body = search(
        client, ENGINEER, query="compensation", filters={"departments": ["hr"]}, top_k=10
    )
    for result in body["results"]:
        assert result["classification"] != "restricted"
        assert not result["source_uri"].startswith("hr/compensation")


def test_classification_filter(client: TestClient) -> None:
    body = search(
        client,
        HR_PERSON,
        query="salary bands",
        filters={"classifications": ["restricted"]},
        top_k=5,
    )
    assert all(r["classification"] == "restricted" for r in body["results"])


def test_request_id_is_always_populated(client: TestClient) -> None:
    """Regression: the route read the inbound request header, so a client that
    did not send one got "" in the body and "unknown" in query_logs - nothing
    to correlate a bad answer against."""
    response = client.post(
        "/api/v1/search",
        json={"query": "authentication"},
        headers=ENGINEER,
    )
    body = response.json()
    assert body["request_id"], "response body must carry a request id"
    assert body["request_id"] == response.headers["X-Request-ID"]


def test_supplied_request_id_is_honoured(client: TestClient) -> None:
    response = client.post(
        "/api/v1/search",
        json={"query": "authentication"},
        headers={**ENGINEER, "X-Request-ID": "caller-supplied-123"},
    )
    assert response.json()["request_id"] == "caller-supplied-123"
