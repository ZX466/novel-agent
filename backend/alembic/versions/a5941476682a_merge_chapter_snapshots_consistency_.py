"""merge chapter_snapshots + consistency_checks heads

Revision ID: a5941476682a
Revises: 1a2b3c4d5e6f, f6a7b8c9d0e1
Create Date: 2026-08-19 18:25:03.088423

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a5941476682a'
down_revision: Union[str, None] = ('1a2b3c4d5e6f', 'f6a7b8c9d0e1')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
