"""Syncing a source, against the real database.

What separates a sync from "read a folder once": unchanged documents must cost
nothing, and documents deleted at the source must stop being retrievable here.
The second is a security property, not housekeeping - a file taken down for a
reason that still answers questions is the same failure as a leak.

Each test uses its own source name so the deletion sweep can never touch the
demo corpus.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import yaml
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.identity import resolve_identity
from app.db.models import Chunk, Document
from app.db.session import SessionLocal
from app.ingestion.connectors import LocalFolderConnector
from app.ingestion.pipeline import IngestionPipeline
from app.retrieval.embedder import get_embedder
from app.services.search_service import SearchService
from tests.integration.conftest import requires_corpus

pytestmark = [pytest.mark.integration, requires_corpus]


@pytest.fixture
def session() -> Session:
    with SessionLocal() as s:
        yield s


@pytest.fixture
def source_name() -> str:
    return f"test-source-{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def cleanup(session: Session, source_name: str):
    yield
    ids = session.execute(select(Document.id).where(Document.source == source_name)).scalars().all()
    if ids:
        session.execute(delete(Chunk).where(Chunk.document_id.in_(ids)))
        session.execute(delete(Document).where(Document.id.in_(ids)))
        session.commit()


def build_corpus(root: Path, documents: dict[str, str], groups: list[str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    entries = []
    for name, body in documents.items():
        (root / name).write_text(body, encoding="utf-8")
        entries.append(
            {
                "path": name,
                "title": name.replace(".md", "").title(),
                "source_type": "markdown",
                "department": "engineering",
                "doc_type": "policy",
                "owner": "priya.raman@northwind.example",
                "classification": "internal",
                "access_groups": groups,
            }
        )
    (root / "manifest.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "company": "Test",
                "groups": ["engineering", "hr", "all-employees", "finance", "legal"],
                "documents": entries,
            }
        ),
        encoding="utf-8",
    )
    return root


def pipeline(session: Session) -> IngestionPipeline:
    return IngestionPipeline(session, get_embedder())


BODY_A = "# Alpha\n\nThe alpha widget runs on port 8421 and is owned by platform.\n"
BODY_B = "# Beta\n\nThe beta widget uses protocol ZX9 for replication.\n"


def test_unchanged_documents_are_skipped_without_re_embedding(
    session: Session, tmp_path: Path, source_name: str
) -> None:
    corpus = build_corpus(tmp_path / "c", {"a.md": BODY_A}, ["engineering"])
    connector = LocalFolderConnector(corpus, name=source_name)

    first = pipeline(session).sync(connector)
    assert first.ingested == 1

    second = pipeline(session).sync(connector)
    assert second.unchanged == 1
    assert second.ingested == 0
    assert second.updated == 0


def test_changed_content_is_re_ingested(session: Session, tmp_path: Path, source_name: str) -> None:
    corpus = build_corpus(tmp_path / "c", {"a.md": BODY_A}, ["engineering"])
    connector = LocalFolderConnector(corpus, name=source_name)
    pipeline(session).sync(connector)

    (corpus / "a.md").write_text(BODY_A + "\n## New section\n\nAdded later.\n", encoding="utf-8")
    report = pipeline(session).sync(connector)
    assert report.updated == 1


def test_a_document_removed_at_the_source_stops_being_retrievable(
    session: Session, tmp_path: Path, source_name: str
) -> None:
    corpus = build_corpus(tmp_path / "c", {"a.md": BODY_A, "b.md": BODY_B}, ["engineering"])
    connector = LocalFolderConnector(corpus, name=source_name)
    pipeline(session).sync(connector)

    identity = resolve_identity(session, "priya.raman@northwind.example")
    found = SearchService(session, get_embedder()).search(
        query="protocol ZX9 replication", identity=identity, top_k=10
    )
    assert any("b.md" in c.source_uri for c in found.candidates), "setup failed"

    # The source no longer has it.
    (corpus / "b.md").unlink()
    build_corpus(tmp_path / "c", {"a.md": BODY_A}, ["engineering"])

    report = pipeline(session).sync(connector)
    assert report.removed == 1

    document = session.execute(
        select(Document).where(Document.source == source_name, Document.source_uri == "b.md")
    ).scalar_one()
    assert document.status == "deleted"
    assert (
        session.execute(
            select(func.count(Chunk.id)).where(Chunk.document_id == document.id)
        ).scalar_one()
        == 0
    )

    after = SearchService(session, get_embedder()).search(
        query="protocol ZX9 replication", identity=identity, top_k=10
    )
    assert not any("b.md" in c.source_uri for c in after.candidates)


def test_pruning_one_source_leaves_others_alone(
    session: Session, tmp_path: Path, source_name: str
) -> None:
    """The demo corpus must survive a sync of an unrelated source."""
    before = session.execute(
        select(func.count(Document.id)).where(
            Document.source == "local-corpus", Document.status == "active"
        )
    ).scalar_one()

    corpus = build_corpus(tmp_path / "c", {"a.md": BODY_A}, ["engineering"])
    pipeline(session).sync(LocalFolderConnector(corpus, name=source_name))

    after = session.execute(
        select(func.count(Document.id)).where(
            Document.source == "local-corpus", Document.status == "active"
        )
    ).scalar_one()
    assert after == before


def test_access_groups_from_the_source_are_enforced(
    session: Session, tmp_path: Path, source_name: str
) -> None:
    """A source declaring hr-only must be unreachable by engineering."""
    corpus = build_corpus(tmp_path / "c", {"secret.md": BODY_B}, ["hr"])
    pipeline(session).sync(LocalFolderConnector(corpus, name=source_name))

    engineer = resolve_identity(session, "priya.raman@northwind.example")
    hr = resolve_identity(session, "marcus.webb@northwind.example")
    service = SearchService(session, get_embedder())

    seen_by_engineer = service.search(query="protocol ZX9 replication", identity=engineer, top_k=10)
    assert not any("secret.md" in c.source_uri for c in seen_by_engineer.candidates)

    seen_by_hr = service.search(query="protocol ZX9 replication", identity=hr, top_k=10)
    assert any("secret.md" in c.source_uri for c in seen_by_hr.candidates)


def test_changing_access_groups_takes_effect_without_re_embedding(
    session: Session, tmp_path: Path, source_name: str
) -> None:
    """An ACL change must not require re-embedding the document."""
    corpus = build_corpus(tmp_path / "c", {"a.md": BODY_A}, ["hr"])
    connector = LocalFolderConnector(corpus, name=source_name)
    pipeline(session).sync(connector)

    build_corpus(tmp_path / "c", {"a.md": BODY_A}, ["engineering"])
    report = pipeline(session).sync(connector)
    assert report.updated + report.unchanged == 1

    engineer = resolve_identity(session, "priya.raman@northwind.example")
    found = SearchService(session, get_embedder()).search(
        query="alpha widget port 8421", identity=engineer, top_k=10
    )
    assert any("a.md" in c.source_uri for c in found.candidates)
