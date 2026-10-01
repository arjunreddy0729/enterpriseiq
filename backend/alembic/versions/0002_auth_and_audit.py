"""auth and audit

Password login, a per-request record of which documents were retrieved, and an
append-only history of permission changes.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.Text(), nullable=True))

    op.add_column(
        "query_logs",
        sa.Column(
            "retrieved_document_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("'{}'::uuid[]"),
        ),
    )
    op.create_index(
        "ix_query_logs_retrieved_document_ids",
        "query_logs",
        ["retrieved_document_ids"],
        postgresql_using="gin",
    )
    # Backfill from rows written before this column existed. used_chunk_ids
    # is the best record they have of what was returned.
    op.execute(
        """
        UPDATE query_logs q
        SET retrieved_document_ids = sub.doc_ids
        FROM (
            SELECT q2.id, array_agg(DISTINCT c.document_id) AS doc_ids
            FROM query_logs q2
            JOIN chunks c ON c.id = ANY (q2.used_chunk_ids)
            GROUP BY q2.id
        ) sub
        WHERE q.id = sub.id
        """
    )

    op.create_table(
        "permission_changes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("actor_email", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=False),
        sa.Column("target_label", sa.Text(), nullable=False),
        sa.Column("before", postgresql.JSONB(), nullable=False),
        sa.Column("after", postgresql.JSONB(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_permission_changes"),
        sa.CheckConstraint(
            "action IN ('document_acl', 'user_groups')", name="ck_permission_changes_action"
        ),
    )
    op.create_index("ix_permission_changes_created_at", "permission_changes", ["created_at"])
    op.create_index("ix_permission_changes_target", "permission_changes", ["target_id"])

    # Append-only, enforced by the database rather than by convention. An
    # audit trail the application can edit is only as trustworthy as the
    # least careful code path that touches it.
    op.execute(
        """
        CREATE FUNCTION reject_audit_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'permission_changes is append-only (% rejected)', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER permission_changes_append_only
        BEFORE UPDATE OR DELETE ON permission_changes
        FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS permission_changes_append_only ON permission_changes")
    op.execute("DROP FUNCTION IF EXISTS reject_audit_mutation()")
    op.drop_index("ix_permission_changes_target", table_name="permission_changes")
    op.drop_index("ix_permission_changes_created_at", table_name="permission_changes")
    op.drop_table("permission_changes")
    op.drop_index("ix_query_logs_retrieved_document_ids", table_name="query_logs")
    op.drop_column("query_logs", "retrieved_document_ids")
    op.drop_column("users", "password_hash")
