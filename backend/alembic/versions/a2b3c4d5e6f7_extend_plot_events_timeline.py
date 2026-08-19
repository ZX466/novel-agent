"""extend plot_events for timeline graph (R6-2 时间线图谱)

Adds the two fields that let plot events form a causal DAG:
  - in_world_date: free-form in-world timestamp used to order the timeline
  - prev_event_id: self-referencing FK to the causal predecessor event

Revises: f6a7b8c9d0e1 (consistency_checks table, head at migration time).

Revision ID: a2b3c4d5e6f7
Revises: f6a7b8c9d0e1
Create Date: 2026-08-19 17:00:00
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a2b3c4d5e6f7"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "plot_events",
        sa.Column("in_world_date", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "plot_events",
        sa.Column("prev_event_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_plot_events_in_world_date", "plot_events", ["in_world_date"]
    )
    op.create_index("ix_plot_events_prev_event_id", "plot_events", ["prev_event_id"])
    op.create_foreign_key(
        "fk_plot_events_prev_event_id",
        "plot_events",
        "plot_events",
        ["prev_event_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_plot_events_prev_event_id", "plot_events", type_="foreignkey")
    op.drop_index("ix_plot_events_prev_event_id", table_name="plot_events")
    op.drop_index("ix_plot_events_in_world_date", table_name="plot_events")
    op.drop_column("plot_events", "prev_event_id")
    op.drop_column("plot_events", "in_world_date")
