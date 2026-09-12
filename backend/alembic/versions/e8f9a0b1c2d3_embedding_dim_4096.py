"""Grow embedding vector columns from 1024 to 4096 dims.

User's BYOK embedding model outputs 4096-dim vectors (user decision 2026-09-12,
方案 B). All existing rows hold truncated 1024-dim vectors from the OLD model
— they cannot be zero-padded into the new model's space (different embedding
space entirely), so every embedding column is NULLed before the ALTER. Rows
themselves are kept; re-embedding happens lazily via the normal auto-embed
paths (or a full re-ingest).

Revision ID: e8f9a0b1c2d3
Revises: 2a3b4c5d6e7f
Create Date: 2026-09-12
"""
from typing import Union

from alembic import op
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "e8f9a0b1c2d3"
down_revision: Union[str, None] = "2a3b4c5d6e7f"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None

# All tables with an embedding column.
_TABLES = (
    "chapters",
    "characters",
    "world_settings",
    "plot_events",
    "knowledge_docs",
)

_NEW_DIM = 4096


def upgrade() -> None:
    for table in _TABLES:
        # pgvector hard limit: HNSW indexes cap at 2000 dims. At 4096 the
        # index cannot exist — drop it. Personal-scale row counts (hundreds
        # to low thousands) make sequential scans millisecond-fast; revisit
        # halfvec(4096) HNSW if volume ever justifies it.
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_embedding_hnsw")
        # Old vectors came from a different embedding space (truncated 1024
        # from the 4096-dim model at a stale config) — padding them would
        # poison the new space. Null them; re-embed lazily.
        op.execute(f"UPDATE {table} SET embedding = NULL")
        op.alter_column(
            table,
            "embedding",
            type_=Vector(_NEW_DIM),
            postgresql_using="embedding::vector(4096)",
        )


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"UPDATE {table} SET embedding = NULL")
        op.alter_column(
            table,
            "embedding",
            type_=Vector(1024),
            postgresql_using="embedding::vector(1024)",
        )
        op.create_index(
            f"ix_{table}_embedding_hnsw",
            table,
            ["embedding"],
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        )
