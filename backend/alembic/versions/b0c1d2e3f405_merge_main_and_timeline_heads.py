"""merge main heads (a5941476682a) with R6-2 timeline head (a2b3c4d5e6f7)

Revises: a5941476682a, a2b3c4d5e6f7
Create Date: 2026-08-19 19:05:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b0c1d2e3f405"
down_revision: Union[str, None] = ("a5941476682a", "a2b3c4d5e6f7")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass