"""extend documents for novel management

Adds columns that turn the bare Tiptap document into a蛙蛙写作-style
"work" (作品) record:

    doc_type        — 作品类型 novel/script/video/short (default 'novel')
    category        — 作品分类 长篇/短篇/剧本/视频 (default '')
    metadata_json   — 写作设置 {writing_type, pov, genre, target_audience}
    status          — 软删除状态 active|deleted (default 'active')
    cover_url       — 封面图 URL (占位图/生成封面)
    word_count      — 缓存字数，用于列表卡片展示，避免逐条加载内容

Soft delete: DELETE /v1/documents/{id} sets status='deleted' instead of
removing the row. Restore flips it back; permanent-delete drops the row.

Revision ID: b7c4e1f09a12
Revises: f3a1e9b2c704
Create Date: 2026-07-24 10:00:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b7c4e1f09a12"
down_revision: Union[str, None] = "f3a1e9b2c704"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "doc_type",
            sa.String(length=32),
            nullable=False,
            server_default="novel",
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "category",
            sa.String(length=32),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="active",
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "cover_url",
            sa.String(length=500),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "word_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    # Indexes for the list filters: type+status together (作品列表按类型 + 软删状态
    # 过滤是最高频查询), category separately (Tab 切换).
    op.create_index(
        "ix_documents_doc_type_status",
        "documents",
        ["doc_type", "status"],
    )
    op.create_index("ix_documents_category", "documents", ["category"])


def downgrade() -> None:
    op.drop_index("ix_documents_category", table_name="documents")
    op.drop_index("ix_documents_doc_type_status", table_name="documents")
    op.drop_column("documents", "word_count")
    op.drop_column("documents", "cover_url")
    op.drop_column("documents", "status")
    op.drop_column("documents", "metadata_json")
    op.drop_column("documents", "category")
    op.drop_column("documents", "doc_type")
