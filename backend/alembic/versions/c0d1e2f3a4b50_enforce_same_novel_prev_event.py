"""enforce same-novel predecessor on plot_events (R6-2 评审 P1)

The R6-2 prev_event_id FK referenced plot_events(id) globally, letting an
event point to a predecessor belonging to ANOTHER novel (cross-work edge;
ON DELETE SET NULL could null another work's row; id side-channel). This
replaces it with a composite FK (novel_id, prev_event_id) -> (novel_id, id)
backed by a UNIQUE(novel_id, id) target, so the database itself rejects
cross-novel predecessors. Existing cross-novel edges are nulled first.

Note: the FK is MATCH SIMPLE, so a NULL prev_event_id (root event) is still
allowed. Novel-scoped index on prev_event_id already exists.

Revises: b0c1d2e3f405
Create Date: 2026-08-19 19:06:00
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c0d1e2f3a4b50"
down_revision: Union[str, None] = "b0c1d2e3f405"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Clean up any existing cross-novel predecessor edges before enforcing.
    op.execute(
        "UPDATE plot_events SET prev_event_id = NULL "
        "WHERE prev_event_id IS NOT NULL AND EXISTS ("
        "  SELECT 1 FROM plot_events p2 "
        "  WHERE p2.id = plot_events.prev_event_id "
        "    AND p2.novel_id <> plot_events.novel_id)"
    )
    op.drop_constraint("fk_plot_events_prev_event_id", "plot_events", type_="foreignkey")
    op.create_unique_constraint(
        "uq_plot_events_novel_id_id", "plot_events", ["novel_id", "id"]
    )
    op.create_foreign_key(
        "fk_plot_events_prev_same_novel",
        "plot_events",
        "plot_events",
        ["novel_id", "prev_event_id"],
        ["novel_id", "id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_plot_events_prev_same_novel", "plot_events", type_="foreignkey")
    op.drop_constraint("uq_plot_events_novel_id_id", "plot_events", type_="unique")
    op.create_foreign_key(
        "fk_plot_events_prev_event_id",
        "plot_events",
        "plot_events",
        ["prev_event_id"],
        ["id"],
        ondelete="SET NULL",
    )