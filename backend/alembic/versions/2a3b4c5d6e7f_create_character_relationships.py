"""create character_relationships table with same-novel FK cascade

New table for relationship-tree visualization + "drag-to-rewire" editing
(R9-③). A directed edge between two characters within a novel:

- one edge per ordered pair (novel_id, subject_id, object_id) — unique
- no self-loops — check subject_id <> object_id
- strength in 0..10 — check constraint
- cross-novel edges rejected at DB layer via composite FKs
  (novel_id, subject_id)/(novel_id, object_id) -> characters(novel_id, id),
  backed by a new UNIQUE(novel_id, id) on characters (P1-2)
- deleting a character CASCADEs its incident edges (P1-1)

Revision ID: 2a3b4c5d6e7f
Revises: b7c8d9e0f1a2
Create Date: 2026-09-11
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "2a3b4c5d6e7f"
down_revision: Union[str, None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Composite-key target for the same-novel FKs (P1-2).
    op.create_unique_constraint(
        "uq_characters_novel_id_id",
        "characters",
        ["novel_id", "id"],
    )

    op.create_table(
        "character_relationships",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("novel_id", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("object_id", sa.Integer(), nullable=False),
        sa.Column("relation_type", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("strength", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "novel_id", "subject_id", "object_id",
            name="uq_character_relationships_novel_subj_obj",
        ),
        sa.CheckConstraint(
            "subject_id <> object_id",
            name="ck_character_relationships_no_self_loop",
        ),
        sa.CheckConstraint(
            "strength >= 0 AND strength <= 10",
            name="ck_character_relationships_strength_range",
        ),
        sa.ForeignKeyConstraint(
            ["novel_id", "subject_id"],
            ["characters.novel_id", "characters.id"],
            name="fk_character_relationships_subject_same_novel",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["novel_id", "object_id"],
            ["characters.novel_id", "characters.id"],
            name="fk_character_relationships_object_same_novel",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_character_relationships_novel_id",
        "character_relationships",
        ["novel_id"],
    )
    op.create_index(
        "ix_character_relationships_subject_id",
        "character_relationships",
        ["subject_id"],
    )
    op.create_index(
        "ix_character_relationships_object_id",
        "character_relationships",
        ["object_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_character_relationships_object_id", table_name="character_relationships"
    )
    op.drop_index(
        "ix_character_relationships_subject_id", table_name="character_relationships"
    )
    op.drop_index(
        "ix_character_relationships_novel_id", table_name="character_relationships"
    )
    op.drop_table("character_relationships")
    op.drop_constraint(
        "uq_characters_novel_id_id", "characters", type_="unique"
    )
