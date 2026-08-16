"""add document API-key ownership scope

Revision ID: c4d5e6f7a8b9
Revises: a1b2c3d4e5f6
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing rows are deliberately assigned no usable owner. An operator
    # must explicitly migrate them to a known API-key hash before exposing
    # the deployment, avoiding an accidental cross-tenant data disclosure.
    op.add_column(
        "documents",
        sa.Column("owner_key_hash", sa.String(length=64), nullable=False, server_default=""),
    )
    op.create_index("ix_documents_owner_key_hash", "documents", ["owner_key_hash"])
    op.alter_column("documents", "owner_key_hash", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_documents_owner_key_hash", table_name="documents")
    op.drop_column("documents", "owner_key_hash")
