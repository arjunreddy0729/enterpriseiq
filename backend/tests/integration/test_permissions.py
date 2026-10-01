"""Permission enforcement, against the real database and the real index.

This is the test suite the project exists to be able to write.

The approach is adversarial rather than illustrative. Instead of asking a
plausible question and checking the answer looks fine, each test takes the
*actual text of a restricted chunk* and uses it as the query. That is the
strongest possible retrieval signal - the query and the document are the same
words, so the chunk is guaranteed to be the nearest neighbour and the top
keyword match. If the access predicate has any hole at all, this finds it.

Requires an ingested corpus:

    python -m scripts.ingest_corpus
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.identity import resolve_identity
from app.db.models import Chunk, Document, Group
from app.db.session import SessionLocal
from app.ingestion.manifest import load_manifest
from app.retrieval.embedder import get_embedder
from app.retrieval.keyword import KeywordRetriever
from app.retrieval.pipeline import HybridRetrievalPipeline
from app.retrieval.types import RetrievalQuery
from app.retrieval.vector import VectorRetriever
from tests.integration.conftest import requires_corpus

pytestmark = [pytest.mark.integration, requires_corpus]


ENGINEER = "priya.raman@northwind.example"
HR_PERSON = "marcus.webb@northwind.example"
FINANCE = "dana.okafor@northwind.example"
LEGAL = "tom.lindqvist@northwind.example"
DUAL_ROLE = "sofia.reyes@northwind.example"  # engineering AND finance
ADMIN = "admin@northwind.example"


@pytest.fixture
def session() -> Session:
    with SessionLocal() as s:
        yield s


def restricted_chunk_texts(session: Session, source_uri: str, limit: int = 4) -> list[str]:
    """The literal text of a document's chunks - used as adversarial queries."""
    return list(
        session.execute(
            select(Chunk.content)
            .join(Document, Document.id == Chunk.document_id)
            .where(Document.source_uri == source_uri)
            .order_by(Chunk.chunk_index)
            .limit(limit)
        ).scalars()
    )


def search_uris(session: Session, email: str, query: str, top_k: int = 20) -> set[str]:
    identity = resolve_identity(session, email)
    pipeline = HybridRetrievalPipeline(session, get_embedder())
    result = pipeline.retrieve(text=query, allowed_group_ids=identity.group_ids, top_k=top_k)
    return {c.source_uri for c in result.candidates}


# ---------------------------------------------------------------------------
# The headline case
# ---------------------------------------------------------------------------
def test_engineer_cannot_retrieve_hr_compensation_policy(session: Session) -> None:
    """Query with the restricted document's own words. It must still not appear."""
    for text in restricted_chunk_texts(session, "hr/compensation-policy.md"):
        found = search_uris(session, ENGINEER, text[:400])
        assert "hr/compensation-policy.md" not in found


def test_hr_can_retrieve_it(session: Session) -> None:
    """The mirror image - otherwise the test above passes on a broken index."""
    texts = restricted_chunk_texts(session, "hr/compensation-policy.md")
    hits = ["hr/compensation-policy.md" in search_uris(session, HR_PERSON, t[:400]) for t in texts]
    assert any(hits), "HR must be able to retrieve their own restricted policy"


# ---------------------------------------------------------------------------
# Every restricted document, every unauthorised user
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "email,forbidden",
    [
        (ENGINEER, "hr/compensation-policy.md"),
        (ENGINEER, "hr/performance-review-process.md"),
        (ENGINEER, "finance/procurement-thresholds.md"),
        (ENGINEER, "finance/revenue-recognition.md"),
        (ENGINEER, "legal/security-incident-legal-playbook.md"),
        (HR_PERSON, "engineering/authentication.md"),
        (HR_PERSON, "finance/revenue-recognition.md"),
        (FINANCE, "hr/compensation-policy.md"),
        (FINANCE, "engineering/payment-service.md"),
        (LEGAL, "hr/compensation-policy.md"),
        (LEGAL, "engineering/deployment-runbook.md"),
    ],
)
def test_restricted_documents_are_unreachable(session: Session, email: str, forbidden: str) -> None:
    for text in restricted_chunk_texts(session, forbidden, limit=3):
        assert forbidden not in search_uris(session, email, text[:400])


def test_dual_role_user_sees_the_union_of_their_groups(session: Session) -> None:
    """Sofia is in engineering AND finance - this exercises array overlap
    rather than single-group equality."""
    finance_text = restricted_chunk_texts(session, "finance/procurement-thresholds.md")[0]
    assert "finance/procurement-thresholds.md" in search_uris(
        session, DUAL_ROLE, finance_text[:400]
    )

    eng_text = restricted_chunk_texts(session, "engineering/authentication.md")[0]
    assert "engineering/authentication.md" in search_uris(session, DUAL_ROLE, eng_text[:400])

    # ...but still not HR.
    hr_text = restricted_chunk_texts(session, "hr/compensation-policy.md")[0]
    assert "hr/compensation-policy.md" not in search_uris(session, DUAL_ROLE, hr_text[:400])


def test_admin_sees_everything(session: Session) -> None:
    for uri in (
        "hr/compensation-policy.md",
        "finance/revenue-recognition.md",
        "legal/security-incident-legal-playbook.md",
        "engineering/authentication.md",
    ):
        text = restricted_chunk_texts(session, uri)[0]
        assert uri in search_uris(session, ADMIN, text[:400])


# ---------------------------------------------------------------------------
# The degenerate cases
# ---------------------------------------------------------------------------
def test_a_user_in_no_groups_retrieves_nothing(session: Session) -> None:
    """Zero results, not everything. An empty IN-list is the classic way this
    goes wrong."""
    pipeline = HybridRetrievalPipeline(session, get_embedder())
    result = pipeline.retrieve(text="authentication", allowed_group_ids=())
    assert result.candidates == []
    assert result.keyword_count == 0
    assert result.vector_count == 0


def test_both_retrievers_enforce_the_predicate_independently(session: Session) -> None:
    """Fusion must not be the thing that enforces access. If either retriever
    leaked, a change to fusion could expose it."""
    identity = resolve_identity(session, ENGINEER)
    text = restricted_chunk_texts(session, "hr/compensation-policy.md")[0][:400]

    query = RetrievalQuery(text=text, allowed_group_ids=identity.group_ids, limit=50)

    keyword_hits = KeywordRetriever(session).search(query)
    vector_hits = VectorRetriever(session, get_embedder()).search(query)

    assert all(c.source_uri != "hr/compensation-policy.md" for c in keyword_hits)
    assert all(c.source_uri != "hr/compensation-policy.md" for c in vector_hits)


def unique_markers(session: Session, source_uri: str) -> list[str]:
    """Text fragments that appear in this document and nowhere else.

    Naively slicing the first 80 characters of each chunk does not work: every
    document in the corpus ends with the same "## Revision History | Date |
    Author | Change |" boilerplate, so such a marker matches innocent chunks
    from documents the caller is fully entitled to read, and the test reports
    a leak that is not there. Each candidate marker is therefore verified
    against the whole corpus first.
    """
    contents = session.execute(
        select(Chunk.content)
        .join(Document, Document.id == Chunk.document_id)
        .where(Document.source_uri == source_uri)
    ).scalars()

    markers: list[str] = []
    for content in contents:
        for line in content.splitlines():
            stripped = line.strip()
            # Long prose lines only: skip headings, table rows and code.
            if len(stripped) < 60 or stripped[0] in "|#`-*>":
                continue
            owners = (
                session.execute(
                    select(Document.source_uri)
                    .join(Chunk, Chunk.document_id == Document.id)
                    .where(Chunk.content.contains(stripped[:60]))
                    .distinct()
                )
                .scalars()
                .all()
            )
            if owners == [source_uri]:
                markers.append(stripped[:60])
                break
    return markers


def test_restricted_text_never_reaches_the_caller(session: Session) -> None:
    """Not just 'the document is absent' - no restricted *text* may appear in
    any returned chunk body."""
    markers = unique_markers(session, "hr/compensation-policy.md")
    assert markers, "no distinctive text found - the test would prove nothing"

    identity = resolve_identity(session, ENGINEER)
    pipeline = HybridRetrievalPipeline(session, get_embedder())

    for query in ("compensation bands", "bonus target by level", "equity refresh grant"):
        result = pipeline.retrieve(text=query, allowed_group_ids=identity.group_ids, top_k=20)
        body = "\n".join(c.content for c in result.candidates)
        for marker in markers:
            assert marker not in body


# ---------------------------------------------------------------------------
# The database must agree with the manifest
# ---------------------------------------------------------------------------
def test_chunk_acls_match_the_manifest(session: Session) -> None:
    """Every chunk's denormalised group ids must equal its document's manifest
    access_groups. A drift here is a silent permission change."""
    from app.core.config import get_settings

    manifest = load_manifest(get_settings().corpus_dir / "manifest.yaml")
    name_by_id = {row.id: row.name for row in session.execute(select(Group.id, Group.name))}

    for entry in manifest.documents:
        rows = session.execute(
            select(Chunk.access_group_ids)
            .join(Document, Document.id == Chunk.document_id)
            .where(Document.source_uri == entry.path)
        ).scalars()
        expected = set(entry.access_groups)
        for group_ids in rows:
            assert {name_by_id[i] for i in group_ids} == expected, entry.path


def test_every_chunk_has_at_least_one_group(session: Session) -> None:
    """A chunk readable by nobody is invisible content - a silent data loss
    that no search would ever reveal."""
    orphans = session.execute(
        select(func.count(Chunk.id)).where(func.cardinality(Chunk.access_group_ids) == 0)
    ).scalar_one()
    assert orphans == 0
