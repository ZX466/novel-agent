"""create chapter_snapshots table (R5-4 ????)

One row per point-in-time copy of a chapter's text, auto-created before
AI insert / whole-chapter replace / export and on manual save. Scoped by
owner_key_hash (tenant) + novel_id (document) + chapter_id, same pattern
as knowledge_docs.

Revision ID: 1a2b3c4d5e6f
Revises: e5f6a7b8c9d0
Create Date: 2026-08-18
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1a2b3c4d5e6f"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chapter_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "owner_key_hash", sa.String(length=64), nullable=False, server_default=""
        ),
        sa.Column("novel_id", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chapter_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("content_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("word_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reason", sa.String(length=32), nullable=False, server_default="save"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chapter_snapshots_owner_key_hash", "chapter_snapshots", ["owner_key_hash"]
    )
    op.create_index(
        "ix_chapter_snapshots_novel_id", "chapter_snapshots", ["novel_id"]
    )
    op.create_index(
        "ix_chapter_snapshots_chapter_id", "chapter_snapshots", ["chapter_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_chapter_snapshots_chapter_id", table_name="chapter_snapshots"
    )
    op.drop_index(
        "ix_chapter_snapshots_novel_id", table_name="chapter_snapshots"
    )
    op.drop_index(
        "ix_chapter_snapshots_owner_key_hash", table_name="chapter_snapshots"
    )
    op.drop_table("chapter_snapshots")
