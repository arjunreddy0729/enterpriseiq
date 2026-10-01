"""Revoking access takes effect on the very next request, and leaves a trail.

These tests change real ACLs in the shared database, so every one restores
what it changed in a `finally`. If one is interrupted mid-run,
`python -m scripts.ingest_corpus` resets every ACL to the manifest.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.db.models import Chunk, Document, User
from app.db.session import SessionLocal
from tests.integration.conftest import login, requires_corpus

pytestmark = [pytest.mark.integration, requires_corpus]

HR_PERSON = "marcus.webb@northwind.example"
ENGINEER = "priya.raman@northwind.example"
ADMIN = "admin@northwind.example"
COMP_POLICY = "hr/compensation-policy.md"


@pytest.fixture
def session() -> Iterator[Session]:
    with SessionLocal() as s:
        yield s


@pytest.fixture
def admin(client: TestClient) -> dict[str, str]:
    return login(client, ADMIN)


def document_id(session: Session, uri: str) -> str:
    return str(session.execute(select(Document.id).where(Document.source_uri == uri)).scalar_one())


def probe_text(session: Session, uri: str) -> str:
    """The document's own words: the strongest query there is for it."""
    return session.execute(
        select(Chunk.content)
        .join(Document, Document.id == Chunk.document_id)
        .where(Document.source_uri == uri)
        .order_by(Chunk.chunk_index)
        .limit(1)
    ).scalar_one()[:400]


def search(client: TestClient, headers: dict[str, str], query: str) -> dict:
    response = client.post("/api/v1/search", json={"query": query, "top_k": 50}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def found(body: dict, uri: str) -> bool:
    return any(r["source_uri"] == uri for r in body["results"])


# ---------------------------------------------------------------------------
# Revocation
# ---------------------------------------------------------------------------
def test_document_revocation_applies_to_the_next_query(
    client: TestClient, session: Session, admin: dict[str, str]
) -> None:
    doc_id = document_id(session, COMP_POLICY)
    query = probe_text(session, COMP_POLICY)
    hr = login(client, HR_PERSON)
    url = f"/api/v1/admin/documents/{doc_id}/permissions"
    original = client.get(url, headers=admin).json()["groups"]

    assert found(search(client, hr, query), COMP_POLICY), "precondition: HR can read it"
    try:
        revoked = client.put(url, json={"groups": ["legal"]}, headers=admin)
        assert revoked.status_code == 200
        assert revoked.json()["groups"] == ["legal"]

        # Same token, same query, immediately after the commit.
        assert not found(search(client, hr, query), COMP_POLICY)
    finally:
        client.put(url, json={"groups": original}, headers=admin)

    assert found(search(client, hr, query), COMP_POLICY), "restoring must restore access"


def test_removing_a_user_from_a_group_beats_their_existing_token(
    client: TestClient, session: Session, admin: dict[str, str]
) -> None:
    """The token was issued while Marcus was in HR. It is still valid and
    unexpired, and it no longer grants HR documents, because the token never
    said anything about groups."""
    hr_token = login(client, HR_PERSON)
    user_id = session.execute(select(User.id).where(User.email == HR_PERSON)).scalar_one()
    url = f"/api/v1/admin/users/{user_id}/groups"
    query = probe_text(session, COMP_POLICY)

    try:
        changed = client.put(url, json={"groups": ["all-employees"]}, headers=admin)
        assert changed.status_code == 200

        assert not found(search(client, hr_token, query), COMP_POLICY)
        assert "hr" not in client.get("/api/v1/auth/me", headers=hr_token).json()["groups"]
    finally:
        client.put(url, json={"groups": ["hr", "all-employees"]}, headers=admin)

    assert found(search(client, hr_token, query), COMP_POLICY)


def test_chunk_copies_change_in_the_same_transaction(
    client: TestClient, session: Session, admin: dict[str, str]
) -> None:
    """document_permissions and chunks.access_group_ids must never disagree."""
    doc_id = document_id(session, COMP_POLICY)
    url = f"/api/v1/admin/documents/{doc_id}/permissions"
    original = client.get(url, headers=admin).json()["groups"]
    try:
        client.put(url, json={"groups": ["legal", "hr"]}, headers=admin)
        rows = (
            session.execute(
                text(
                    """
                SELECT DISTINCT c.access_group_ids
                FROM chunks c WHERE c.document_id = :doc
                """
                ),
                {"doc": doc_id},
            )
            .scalars()
            .all()
        )
        expected = session.execute(
            text(
                """
                SELECT array_agg(group_id ORDER BY group_id)
                FROM document_permissions WHERE document_id = :doc
                """
            ),
            {"doc": doc_id},
        ).scalar_one()
        assert [sorted(r) for r in rows] == [sorted(expected)]
    finally:
        client.put(url, json={"groups": original}, headers=admin)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def test_a_document_cannot_be_made_readable_by_nobody(
    client: TestClient, session: Session, admin: dict[str, str]
) -> None:
    url = f"/api/v1/admin/documents/{document_id(session, COMP_POLICY)}/permissions"
    response = client.put(url, json={"groups": []}, headers=admin)
    assert response.status_code == 400


def test_unknown_groups_are_rejected_not_skipped(
    client: TestClient, session: Session, admin: dict[str, str]
) -> None:
    url = f"/api/v1/admin/documents/{document_id(session, COMP_POLICY)}/permissions"
    response = client.put(url, json={"groups": ["hr", "hr-typo"]}, headers=admin)
    assert response.status_code == 400
    assert client.get(url, headers=admin).json()["groups"] == ["hr"]


def test_non_admins_cannot_change_permissions(client: TestClient, session: Session) -> None:
    url = f"/api/v1/admin/documents/{document_id(session, COMP_POLICY)}/permissions"
    response = client.put(url, json={"groups": ["engineering"]}, headers=login(client, ENGINEER))
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------
def test_audit_shows_who_retrieved_a_document(
    client: TestClient, session: Session, admin: dict[str, str]
) -> None:
    doc_id = document_id(session, COMP_POLICY)
    body = search(client, login(client, HR_PERSON), probe_text(session, COMP_POLICY))
    assert found(body, COMP_POLICY)

    report = client.get(
        f"/api/v1/admin/audit/documents/{doc_id}", params={"days": 1}, headers=admin
    ).json()
    event = next(e for e in report["events"] if e["request_id"] == body["request_id"])
    assert event["user_email"] == HR_PERSON
    assert event["endpoint"] == "search"
    assert event["shown_to_user"] is True


def test_a_denied_user_does_not_appear_in_the_audit(
    client: TestClient, session: Session, admin: dict[str, str]
) -> None:
    """The engineer's search ran, but the document never left the database
    for them, so they are not in its access report."""
    doc_id = document_id(session, COMP_POLICY)
    body = search(client, login(client, ENGINEER), probe_text(session, COMP_POLICY))

    report = client.get(
        f"/api/v1/admin/audit/documents/{doc_id}", params={"days": 1}, headers=admin
    ).json()
    assert body["request_id"] not in {e["request_id"] for e in report["events"]}


def test_permission_changes_are_recorded_with_before_and_after(
    client: TestClient, session: Session, admin: dict[str, str]
) -> None:
    doc_id = document_id(session, COMP_POLICY)
    url = f"/api/v1/admin/documents/{doc_id}/permissions"
    original = client.get(url, headers=admin).json()["groups"]
    try:
        client.put(url, json={"groups": ["hr", "legal"]}, headers=admin)
    finally:
        client.put(url, json={"groups": original}, headers=admin)

    history = client.get(
        "/api/v1/admin/audit/permission-changes", params={"limit": 2}, headers=admin
    ).json()
    grant, restore = history[1], history[0]
    assert grant["target_label"] == COMP_POLICY
    assert grant["actor_email"] == ADMIN
    assert grant["before"] == original
    assert grant["after"] == ["hr", "legal"]
    assert restore["after"] == original


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE permission_changes SET actor_email = 'someone-else@example.com'",
        "DELETE FROM permission_changes",
    ],
)
def test_the_permission_history_cannot_be_rewritten(session: Session, statement: str) -> None:
    """Enforced by a database trigger, so not even a bug in the app can do it."""
    with pytest.raises(DBAPIError, match="append-only"):
        session.execute(text(statement))
    session.rollback()
