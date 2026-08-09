"""Schema and seed integration tests.

These run against a live PostgreSQL and skip cleanly when one is not up:

    docker compose up -d db
    pytest -m integration

Testing the schema against a real database (rather than mocking SQLAlchemy) is
the point: the parts most likely to break - the pgvector extension, the
generated tsvector column, the GIN and HNSW indexes, the ACL array overlap
operator - do not exist at all in a mock.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings

pytestmark = pytest.mark.integration


EXPECTED_TABLES = {
    "alembic_version",
    "groups",
    "users",
    "user_groups",
    "documents",
    "document_permissions",
    "chunks",
    "term_stats",
    "corpus_stats",
    "query_logs",
}

EXPECTED_INDEXES = {
    "ix_chunks_tsv",
    "ix_chunks_access_group_ids",
    "ix_chunks_embedding_hnsw",
    "ix_chunks_document_id",
    "ux_documents_source_uri",
}


class TestExtensions:
    def test_pgvector_is_installed(self, db_session: Session) -> None:
        version = db_session.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        ).scalar_one_or_none()
        assert version is not None, "run `alembic upgrade head`"


class TestSchema:
    def test_all_tables_exist(self, db_session: Session) -> None:
        rows = db_session.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        ).scalars()
        assert set(rows) >= EXPECTED_TABLES

    def test_all_indexes_exist(self, db_session: Session) -> None:
        rows = db_session.execute(
            text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
        ).scalars()
        assert set(rows) >= EXPECTED_INDEXES

    def test_embedding_column_dimension_matches_configuration(
        self, db_session: Session, settings: Settings
    ) -> None:
        # pgvector stores the declared dimension in pg_attribute.atttypmod.
        typmod = db_session.execute(
            text(
                "SELECT atttypmod FROM pg_attribute "
                "WHERE attrelid = 'public.chunks'::regclass "
                "AND attname = 'embedding' AND NOT attisdropped"
            )
        ).scalar_one()
        assert typmod == settings.embedding_dim

    def test_tsv_is_a_stored_generated_column(self, db_session: Session) -> None:
        # If this were an ordinary column the application would have to
        # maintain it, and it would eventually drift from `content`.
        generated = db_session.execute(
            text(
                "SELECT is_generated FROM information_schema.columns "
                "WHERE table_name = 'chunks' AND column_name = 'tsv'"
            )
        ).scalar_one()
        assert generated == "ALWAYS"

    def test_hnsw_index_uses_cosine_distance(self, db_session: Session) -> None:
        definition = db_session.execute(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_chunks_embedding_hnsw'")
        ).scalar_one()
        assert "hnsw" in definition
        assert "vector_cosine_ops" in definition

    def test_acl_and_tsv_indexes_are_gin(self, db_session: Session) -> None:
        for name in ("ix_chunks_tsv", "ix_chunks_access_group_ids"):
            definition = db_session.execute(
                text("SELECT indexdef FROM pg_indexes WHERE indexname = :n"), {"n": name}
            ).scalar_one()
            assert "USING gin" in definition, name

    def test_source_uri_uniqueness_ignores_deleted_documents(self, db_session: Session) -> None:
        definition = db_session.execute(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ux_documents_source_uri'")
        ).scalar_one()
        assert "UNIQUE" in definition
        assert "WHERE" in definition and "deleted" in definition

    def test_corpus_stats_has_exactly_one_row(self, db_session: Session) -> None:
        count = db_session.execute(text("SELECT count(*) FROM corpus_stats")).scalar_one()
        assert count == 1


class TestMigrationState:
    def test_a_migration_has_been_applied(self, db_session: Session) -> None:
        applied = db_session.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert applied


class TestSeedData:
    def test_all_five_groups_are_seeded(self, db_session: Session) -> None:
        names = set(db_session.execute(text("SELECT name FROM groups")).scalars())
        assert names == {"all-employees", "engineering", "hr", "finance", "legal"}

    def test_users_are_seeded(self, db_session: Session) -> None:
        count = db_session.execute(text("SELECT count(*) FROM users")).scalar_one()
        assert count >= 7

    def test_priya_is_engineering_only(self, db_session: Session) -> None:
        groups = set(
            db_session.execute(
                text(
                    "SELECT g.name FROM groups g "
                    "JOIN user_groups ug ON ug.group_id = g.id "
                    "JOIN users u ON u.id = ug.user_id "
                    "WHERE u.email = :email"
                ),
                {"email": "priya.raman@northwind.example"},
            ).scalars()
        )
        assert groups == {"engineering", "all-employees"}

    def test_sofia_spans_two_departments(self, db_session: Session) -> None:
        groups = set(
            db_session.execute(
                text(
                    "SELECT g.name FROM groups g "
                    "JOIN user_groups ug ON ug.group_id = g.id "
                    "JOIN users u ON u.id = ug.user_id "
                    "WHERE u.email = :email"
                ),
                {"email": "sofia.reyes@northwind.example"},
            ).scalars()
        )
        assert groups == {"engineering", "finance", "all-employees"}

    def test_seeding_is_idempotent(self, db_session: Session) -> None:
        # The entrypoint reruns the seed on every container start.
        from scripts.seed_users import seed_groups, seed_users

        before = db_session.execute(text("SELECT count(*) FROM user_groups")).scalar_one()
        groups = seed_groups(db_session)
        seed_users(db_session, groups)
        db_session.flush()
        after = db_session.execute(text("SELECT count(*) FROM user_groups")).scalar_one()
        assert before == after
        db_session.rollback()


class TestAclPredicate:
    """The `&&` array-overlap operator is the single predicate that enforces
    permission-aware retrieval. Prove it behaves as expected before anything
    is built on top of it."""

    def test_overlap_operator_semantics(self, db_session: Session) -> None:
        overlaps = db_session.execute(
            text("SELECT ARRAY[1,2]::int[] && ARRAY[2,3]::int[]")
        ).scalar_one()
        assert overlaps is True

        disjoint = db_session.execute(
            text("SELECT ARRAY[1,2]::int[] && ARRAY[3,4]::int[]")
        ).scalar_one()
        assert disjoint is False

    def test_empty_user_groups_match_nothing(self, db_session: Session) -> None:
        # A user with no groups must retrieve zero chunks - never "everything".
        result = db_session.execute(text("SELECT ARRAY[1,2]::int[] && ARRAY[]::int[]")).scalar_one()
        assert result is False
