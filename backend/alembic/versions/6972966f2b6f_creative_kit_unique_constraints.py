"""creative kit unique constraints

Create unique constraints (novel_id, title) on world_settings and
(novel_id, name) on characters so concurrent Creative-Kit applies (and any
other create path) can never produce duplicates. Because both tables may
already hold duplicate rows, existing duplicates are removed first keeping
the lowest id (oldest) per (novel_id, title|name).

Revision ID: 6972966f2b6f
Revises: c0d1e2f3a4b50
Create Date: 2026-08-20 17:42:27.337142

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6972966f2b6f'
down_revision: Union[str, None] = 'c0d1e2f3a4b50'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Deduplicate existing rows before adding constraints: keep the row with
    # the lowest id per (novel_id, title) / (novel_id, name).
    op.execute(
        """
        DELETE FROM world_settings a USING world_settings b
        WHERE a.id > b.id
          AND a.novel_id = b.novel_id
          AND a.title = b.title
        """
    )
    op.execute(
        """
        DELETE FROM characters a USING characters b
        WHERE a.id > b.id
          AND a.novel_id = b.novel_id
          AND a.name = b.name
        """
    )
    op.create_unique_constraint(
        "uq_world_settings_novel_title", "world_settings", ["novel_id", "title"]
    )
    op.create_unique_constraint(
        "uq_characters_novel_name", "characters", ["novel_id", "name"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_characters_novel_name", "characters", type_="unique")
    op.drop_constraint("uq_world_settings_novel_title", "world_settings", type_="unique")