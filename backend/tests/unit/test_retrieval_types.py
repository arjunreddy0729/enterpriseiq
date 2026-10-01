"""RetrievalQuery invariants and the access predicate's construction.

No database needed: these check that a retrieval request cannot be built
without deciding who is asking, and that the predicate produced is the array
overlap the schema is indexed for.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy.dialects import postgresql

from app.retrieval.filters import access_predicate, build_where, describe
from app.retrieval.types import Candidate, Filters, RetrievalQuery


def compile_sql(clause: object) -> str:
    return str(
        clause.compile(  # type: ignore[union-attr]
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


# ---------------------------------------------------------------------------
# The query object cannot forget permissions
# ---------------------------------------------------------------------------
def test_allowed_groups_has_no_default() -> None:
    """Omitting access groups must be a TypeError at the call site, not a
    silently unfiltered search at runtime."""
    with pytest.raises(TypeError):
        RetrievalQuery(text="anything")  # type: ignore[call-arg]


def test_a_list_is_rejected() -> None:
    with pytest.raises(TypeError):
        RetrievalQuery(text="x", allowed_group_ids=[1, 2])  # type: ignore[arg-type]


def test_no_groups_means_sees_nothing() -> None:
    query = RetrievalQuery(text="x", allowed_group_ids=())
    assert query.sees_nothing


def test_having_groups_means_not_sees_nothing() -> None:
    assert not RetrievalQuery(text="x", allowed_group_ids=(1,)).sees_nothing


def test_limit_must_be_positive() -> None:
    with pytest.raises(ValueError):
        RetrievalQuery(text="x", allowed_group_ids=(1,), limit=0)


# ---------------------------------------------------------------------------
# The predicate itself
# ---------------------------------------------------------------------------
def test_predicate_is_an_array_overlap() -> None:
    """`&&` is what the GIN index on access_group_ids accelerates."""
    sql = compile_sql(access_predicate(RetrievalQuery(text="x", allowed_group_ids=(2, 7))))
    assert "&&" in sql
    assert "access_group_ids" in sql


def test_no_groups_compiles_to_false_not_to_nothing() -> None:
    """A caller in no groups must match zero rows. The dangerous bug would be
    an empty predicate, which matches everything."""
    sql = compile_sql(access_predicate(RetrievalQuery(text="x", allowed_group_ids=())))
    assert "false" in sql.lower()
    assert "&&" not in sql


def test_build_where_always_includes_the_access_clause() -> None:
    query = RetrievalQuery(
        text="x",
        allowed_group_ids=(3,),
        filters=Filters(departments=("engineering",), doc_types=("runbook",)),
    )
    sql = compile_sql(build_where(query))
    assert "&&" in sql
    assert "engineering" in sql
    assert "runbook" in sql


def test_metadata_filters_are_optional_but_access_is_not() -> None:
    bare = compile_sql(build_where(RetrievalQuery(text="x", allowed_group_ids=(1,))))
    assert "&&" in bare


def test_date_filters_compile() -> None:
    query = RetrievalQuery(
        text="x",
        allowed_group_ids=(1,),
        filters=Filters(updated_after=dt.date(2026, 1, 1), updated_before=dt.date(2026, 6, 1)),
    )
    sql = compile_sql(build_where(query))
    assert "source_updated_at" in sql


def test_describe_reports_the_groups_in_play() -> None:
    described = describe(
        RetrievalQuery(text="x", allowed_group_ids=(4, 5), filters=Filters(departments=("hr",)))
    )
    assert described["allowed_group_ids"] == [4, 5]
    assert described["departments"] == ["hr"]


def test_filters_is_empty() -> None:
    assert Filters().is_empty
    assert not Filters(departments=("hr",)).is_empty


# ---------------------------------------------------------------------------
# Candidate bookkeeping
# ---------------------------------------------------------------------------
def make_candidate() -> Candidate:
    return Candidate(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        content="c",
        embed_text="c",
        section_path=None,
        document_title="t",
        source_uri="t.md",
        department=None,
        doc_type=None,
        classification=None,
        chunk_index=0,
    )


def test_retrieved_by_reflects_which_retrievers_hit() -> None:
    c = make_candidate()
    assert c.retrieved_by == ()
    c.keyword_rank = 1
    assert c.retrieved_by == ("keyword",)
    c.vector_rank = 2
    assert set(c.retrieved_by) == {"keyword", "vector"}


def test_final_score_prefers_the_most_informed_signal() -> None:
    c = make_candidate()
    c.vector_score = 0.5
    assert c.final_score == 0.5
    c.rrf_score = 0.03
    assert c.final_score == 0.03
    c.rerank_score = 9.1
    assert c.final_score == 9.1
