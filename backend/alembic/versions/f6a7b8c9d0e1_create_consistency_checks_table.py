"""create consistency_checks table (R5-3 设定一致性哨兵)

One row per setting-consistency verdict produced when a draft is scanned
against the novel's stored character settings. Mirrors the knowledge_docs
tenant-isolation posture: owner_key_hash + novel_id scope.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-08-18 16:30:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "consistency_checks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("owner_key_hash", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("novel_id", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chapter_id", sa.Integer(), nullable=True),
        sa.Column("target_type", sa.String(length=32), nullable=False, server_default="character"),
        sa.Column("target_id", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("target_name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("verdict", sa.String(length=16), nullable=False, server_default="pass"),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.Column("evidence_type", sa.String(length=32), nullable=True),
        sa.Column("evidence_id", sa.Integer(), nullable=True),
        sa.Column("evidence_snippet", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_consistency_checks_owner_key_hash", "consistency_checks", ["owner_key_hash"])
    op.create_index("ix_consistency_checks_novel_id", "consistency_checks", ["novel_id"])
    op.create_index("ix_consistency_checks_chapter_id", "consistency_checks", ["chapter_id"])


def downgrade() -> None:
    op.drop_index("ix_consistency_checks_chapter_id", table_name="consistency_checks")
    op.drop_index("ix_consistency_checks_novel_id", table_name="consistency_checks")
    op.drop_index("ix_consistency_checks_owner_key_hash", table_name="consistency_checks")
    op.drop_table("consistency_checks")