"""document sources and revisions

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-16

Two columns that turn ingestion from "read a folder" into "sync a source".

`source` records which connector a document came from. Without it there is no
way to answer "which documents does this source still have?", and therefore no
way to notice that one was deleted at the source. A document deleted in
SharePoint that stays retrievable here is a permission bug wearing a different
hat.

`revision` is the source's own cheap change token - a git blob SHA, an ETag, a
modification time. Comparing it skips the download, the parse and the embed
for unchanged documents, which is what makes syncing a large source on a
schedule affordable.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("source", sa.String(length=128), nullable=False, server_default="local-corpus"),
    )
    op.add_column("documents", sa.Column("revision", sa.String(length=128), nullable=True))

    # Scoping a sync's deletion sweep is the whole point of the column, and
    # that sweep filters on exactly this pair.
    op.create_index("ix_documents_source", "documents", ["source", "status"])


def downgrade() -> None:
    op.drop_index("ix_documents_source", table_name="documents")
    op.drop_column("documents", "revision")
    op.drop_column("documents", "source")
