"""Shrink embedding vector columns from 1536 to 1024 dims.

User's BYOK embedding model outputs 1024-dim vectors; 1536-dim columns
forced runtime zero-padding on every row (wasted storage + blurred
distances). All embedding columns are currently NULL everywhere
(verified before writing this migration), so this is a pure ALTER
with no data backfill.

Revision ID: b7c8d9e0f1a2
Revises: 6972966f2b6f
Create Date: 2026-08-28

"""
from typing import Union

from alembic import op
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, None] = "6972966f2b6f"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None

# All tables with an embedding column, from the original memory-tables and
# knowledge-docs migrations (plus any added since).
_TABLES = (
    "chapters",
    "characters",
    "world_settings",
    "plot_events",
    "knowledge_docs",
)

_NEW_DIM = 1024
_OLD_DIM = 1536


def upgrade() -> None:
    for table in _TABLES:
        op.alter_column(
            table,
            "embedding",
            type_=Vector(_NEW_DIM),
            postgresql_using="embedding::vector(1024)",
        )


def downgrade() -> None:
    for table in _TABLES:
        op.alter_column(
            table,
            "embedding",
            type_=Vector(_OLD_DIM),
            postgresql_using="embedding::vector(1536)",
        )
