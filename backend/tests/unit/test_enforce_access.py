"""The application-level ACL re-check that runs after the SQL predicate."""

from __future__ import annotations

import uuid

from app.retrieval.filters import enforce_access
from app.retrieval.types import Candidate


def candidate(groups: tuple[int, ...], uri: str = "doc.md") -> Candidate:
    return Candidate(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        content="text",
        embed_text="text",
        section_path=None,
        document_title="Doc",
        source_uri=uri,
        department=None,
        doc_type=None,
        classification=None,
        chunk_index=0,
        access_group_ids=groups,
    )


def test_permitted_candidates_pass_through_in_order() -> None:
    items = [candidate((1,), "a.md"), candidate((2, 3), "b.md"), candidate((3,), "c.md")]
    assert [c.source_uri for c in enforce_access(items, (1, 3))] == ["a.md", "b.md", "c.md"]


def test_a_candidate_outside_the_callers_groups_is_dropped() -> None:
    """Simulates the SQL predicate failing: the leaked chunk must not survive."""
    items = [candidate((1,), "ok.md"), candidate((9,), "hr-only.md")]
    assert [c.source_uri for c in enforce_access(items, (1,))] == ["ok.md"]


def test_a_chunk_with_no_groups_is_readable_by_nobody() -> None:
    assert enforce_access([candidate(())], (1, 2, 3)) == []


def test_a_caller_with_no_groups_gets_nothing() -> None:
    assert enforce_access([candidate((1,))], ()) == []
