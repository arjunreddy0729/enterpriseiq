"""drop the unused term_stats table

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-16

term_stats was created in 0001 as groundwork for BM25 rescoring over the
full-text candidate set. That rescoring was never built, so the table has
never been written to or read from - zero rows, zero code paths.

Schema for a feature that does not exist is a liability: it reads as working
infrastructure, it has to be migrated and backed up like real data, and it
makes the keyword retriever look closer to BM25 than it is. If the rescoring
lands later it will need a table shaped by what that code actually wants, not
by what seemed plausible a year earlier.

corpus_stats stays: it is populated on every ingest and reports real numbers
about the index.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("term_stats")


def downgrade() -> None:
    op.create_table(
        "term_stats",
        sa.Column("term", sa.Text(), nullable=False),
        sa.Column("document_frequency", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("term"),
    )
