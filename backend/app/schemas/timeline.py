"""Pydantic schemas for the timeline-graph domain (R6-2 时间线图谱).

The timeline view exposes the novel's plot events as a causal DAG: nodes
(events) ordered by in-world date / chapter index, edges following
prev_event_id predecessor pointers, plus any structural warnings (dangling
predecessor, reverse ordering, cycles). `topological_order` is the causal
topological sort of event ids.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TimelineNode(BaseModel):
    """A plot event as a node in the causal DAG."""

    event_id: int
    event_type: str = Field(default="beat")
    summary: str
    chapter_id: int | None = None
    chapter_index: int | None = None
    in_world_date: str | None = None
    prev_event_id: int | None = None


class TimelineEdge(BaseModel):
    """Directed edge `from_id` (predecessor) -> `to_id` (successor)."""

    from_id: int
    to_id: int


class TimelineWarning(BaseModel):
    """A timeline-consistency finding (real-time conflict warning)."""

    model_config = ConfigDict(frozen=True)

    kind: str = Field(..., description="predecessor|reverse_order|cycle")
    event_id: int
    detail: str


class TimelineResponse(BaseModel):
    """Full timeline view for one novel."""

    nodes: list[TimelineNode]
    edges: list[TimelineEdge]
    warnings: list[TimelineWarning]
    topological_order: list[int]
