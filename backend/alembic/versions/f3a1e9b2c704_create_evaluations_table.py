"""create evaluations table

Adds the `evaluations` table that persists quality scores produced at
each evaluation point in the pipeline (draft / refine / final_polish /
consistency_check / reflection / safety / pipeline_evaluate), enabling
quality trend analysis across runs.

Revision ID: f3a1e9b2c704
Revises: a1b2c3d4e5f6
Create Date: 2026-07-21 00:00:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3a1e9b2c704"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "evaluations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("novel_id", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "chapter_id",
            sa.Integer(),
            sa.ForeignKey("chapters.id"),
            nullable=True,
        ),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("feedback", sa.Text(), nullable=False, server_default=""),
        sa.Column("source", sa.String(length=128), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evaluations_novel_id", "evaluations", ["novel_id"])
    op.create_index("ix_evaluations_chapter_id", "evaluations", ["chapter_id"])
    op.create_index("ix_evaluations_stage", "evaluations", ["stage"])


def downgrade() -> None:
    op.drop_index("ix_evaluations_stage", table_name="evaluations")
    op.drop_index("ix_evaluations_chapter_id", table_name="evaluations")
    op.drop_index("ix_evaluations_novel_id", table_name="evaluations")
    op.drop_table("evaluations")
