"""create knowledge_docs table (F4 本地知识库)

One row per ~800-char chunk of an uploaded knowledge-base file. Mirrors the
existing memory-collection shape (novel_id scope + vector embedding + HNSW
cosine index) plus owner_key_hash tenant scope.

Revision ID: e5f6a7b8c9d0
Revises: c4d5e6f7a8b9
Create Date: 2026-08-17 10:00:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIM = 1536


def upgrade() -> None:
    op.create_table(
        "knowledge_docs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("owner_key_hash", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("novel_id", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
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
    op.create_index("ix_knowledge_docs_owner_key_hash", "knowledge_docs", ["owner_key_hash"])
    op.create_index("ix_knowledge_docs_novel_id", "knowledge_docs", ["novel_id"])
    op.create_index("ix_knowledge_docs_title", "knowledge_docs", ["title"])
    op.execute(
        "CREATE INDEX ix_knowledge_docs_embedding_hnsw ON knowledge_docs "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_knowledge_docs_embedding_hnsw")
    op.drop_index("ix_knowledge_docs_title", table_name="knowledge_docs")
    op.drop_index("ix_knowledge_docs_novel_id", table_name="knowledge_docs")
    op.drop_index("ix_knowledge_docs_owner_key_hash", table_name="knowledge_docs")
    op.drop_table("knowledge_docs")
