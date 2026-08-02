"""create novel memory tables (chapters, characters, world_settings, plot_events)

Enables the pgvector extension and creates four ORM-backed tables that
together form the novel-agent memory layer:

    chapters         — chapter content + summary + embedding
    characters       — character profiles + attributes + embedding
    world_settings   — lore entries (geography/history/magic/...) + embedding
    plot_events      — discrete plot beats, linked to chapters + characters

Each embedding column is `vector(1536)` (OpenAI text-embedding-3-small).
The migration creates HNSW indexes for cosine similarity on each
embedding column to keep retrieval fast at scale.

Revision ID: a1b2c3d4e5f6
Revises: d292f6abee87
Create Date: 2026-07-20 23:00:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "d292f6abee87"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIM = 1536


def upgrade() -> None:
    # 1. Enable pgvector extension. `CREATE EXTENSION IF NOT EXISTS` is
    #    idempotent so the migration is safe to re-run on provisioned DBs.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 2. chapters table
    op.create_table(
        "chapters",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("novel_id", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chapter_index", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("word_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
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
    )
    op.create_index("ix_chapters_novel_id", "chapters", ["novel_id"])
    op.create_index("ix_chapters_chapter_index", "chapters", ["chapter_index"])
    op.create_index("ix_chapters_status", "chapters", ["status"])
    # HNSW index for cosine similarity. Use `vector_cosine_ops` operator class.
    op.execute(
        "CREATE INDEX ix_chapters_embedding_hnsw ON chapters "
        "USING hnsw (embedding vector_cosine_ops)"
    )

    # 3. characters table
    op.create_table(
        "characters",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("novel_id", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False, server_default="配角"),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("arc_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
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
    )
    op.create_index("ix_characters_novel_id", "characters", ["novel_id"])
    op.create_index("ix_characters_name", "characters", ["name"])
    op.create_index("ix_characters_role", "characters", ["role"])
    op.execute(
        "CREATE INDEX ix_characters_embedding_hnsw ON characters "
        "USING hnsw (embedding vector_cosine_ops)"
    )

    # 4. world_settings table
    op.create_table(
        "world_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("novel_id", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("category", sa.String(length=64), nullable=False, server_default="misc"),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
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
    )
    op.create_index("ix_world_settings_novel_id", "world_settings", ["novel_id"])
    op.create_index("ix_world_settings_category", "world_settings", ["category"])
    op.execute(
        "CREATE INDEX ix_world_settings_embedding_hnsw ON world_settings "
        "USING hnsw (embedding vector_cosine_ops)"
    )

    # 5. plot_events table
    op.create_table(
        "plot_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("novel_id", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "chapter_id",
            sa.Integer(),
            sa.ForeignKey("chapters.id"),
            nullable=True,
        ),
        sa.Column("chapter_index", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False, server_default="beat"),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "involved_character_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
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
    )
    op.create_index("ix_plot_events_novel_id", "plot_events", ["novel_id"])
    op.create_index("ix_plot_events_chapter_id", "plot_events", ["chapter_id"])
    op.create_index("ix_plot_events_chapter_index", "plot_events", ["chapter_index"])
    op.create_index("ix_plot_events_event_type", "plot_events", ["event_type"])
    op.execute(
        "CREATE INDEX ix_plot_events_embedding_hnsw ON plot_events "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.drop_index("ix_plot_events_embedding_hnsw", table_name="plot_events")
    op.drop_index("ix_plot_events_event_type", table_name="plot_events")
    op.drop_index("ix_plot_events_chapter_index", table_name="plot_events")
    op.drop_index("ix_plot_events_chapter_id", table_name="plot_events")
    op.drop_index("ix_plot_events_novel_id", table_name="plot_events")
    op.drop_table("plot_events")

    op.drop_index("ix_world_settings_embedding_hnsw", table_name="world_settings")
    op.drop_index("ix_world_settings_category", table_name="world_settings")
    op.drop_index("ix_world_settings_novel_id", table_name="world_settings")
    op.drop_table("world_settings")

    op.drop_index("ix_characters_embedding_hnsw", table_name="characters")
    op.drop_index("ix_characters_role", table_name="characters")
    op.drop_index("ix_characters_name", table_name="characters")
    op.drop_index("ix_characters_novel_id", table_name="characters")
    op.drop_table("characters")

    op.drop_index("ix_chapters_embedding_hnsw", table_name="chapters")
    op.drop_index("ix_chapters_status", table_name="chapters")
    op.drop_index("ix_chapters_chapter_index", table_name="chapters")
    op.drop_index("ix_chapters_novel_id", table_name="chapters")
    op.drop_table("chapters")

    # Do NOT drop the pgvector extension on downgrade — other consumers may
    # depend on it. Re-running the migration on a fresh DB re-creates it.
