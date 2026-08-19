"""Timeline-graph service (R6-2 时间线图谱).

Builds the causal DAG of a novel's plot events from their ``prev_event_id``
predecessor pointers plus ``in_world_date`` / ``chapter_index`` ordering, and
exposes real-time conflict warnings on chapter writes.

Pure functions (``build_timeline_dag`` / helpers) are fully unit-testable
without a DB. ``validate_chapter_write`` and ``get_timeline`` load events via
the session so the same logic serves both write-time validation and the
timeline view endpoint.
"""
from __future__ import annotations

import logging
import re
from collections import deque
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.plot_event import PlotEvent
from app.schemas.timeline import TimelineEdge, TimelineNode, TimelineWarning

logger = logging.getLogger(__name__)

_WARN_PREDECESSOR = "predecessor"
_WARN_REVERSE_ORDER = "reverse_order"
_WARN_CYCLE = "cycle"

# Ordering contract for in_world_date (R6-2 P2): parse YYYY / YYYY-MM /
# YYYY-MM-DD plus common CJK separators (年/月/日, /, ., -) and sort by
# (year, month, day). Unparseable values are grouped AFTER all real dates
# and ordered by their raw string — a documented, deterministic contract.
_DATE_RE = re.compile(
    r"^\s*(\d{4})\s*[-/年.]\s*(\d{1,2})?\s*[-/月.]?\s*(\d{1,2})?\s*日?\s*$"
)


@dataclass
class TimelineDag:
    """Result of building the causal DAG of a novel's plot events."""

    nodes: list[TimelineNode] = field(default_factory=list)
    edges: list[TimelineEdge] = field(default_factory=list)
    warnings: list[TimelineWarning] = field(default_factory=list)
    topological_ids: list[int] = field(default_factory=list)


def _date_sort_key(value: str | None) -> tuple:
    """Deterministic date ordering key for ``in_world_date``.

    - ``None`` / empty -> (0,)            unplaced events sort first (roots)
    - parseable date   -> (1, year, month, day)
    - anything else    -> (2, raw)        after all real dates, lexicographic
    """
    if not value:
        return (0,)
    match = _DATE_RE.match(value)
    if match:
        year = int(match.group(1))
        month = int(match.group(2) or 1)
        day = int(match.group(3) or 1)
        return (1, year, month, day)
    return (2, value)


def _sort_key(pe: PlotEvent) -> tuple:
    """Deterministic causal sort: normalized in-world date, then chapter,
    then id. Undated / unplaced events act as timeline roots.
    """
    return (
        _date_sort_key(pe.in_world_date),
        pe.chapter_index if pe.chapter_index is not None else -1,
        pe.id,
    )


def _violates_causal_order(prev: PlotEvent, cur: PlotEvent) -> bool:
    """True when the causal predecessor is placed AFTER its successor.

    Compares by chapter_index when both are placed (strictly earlier chapter
    required; two events chained within the SAME chapter are valid). Falls
    back to normalized in_world_date when both carry dates. Mixed signals
    (one has a date, the other only a chapter) are not comparable — returns
    False.
    """
    if prev.chapter_index is not None and cur.chapter_index is not None:
        return prev.chapter_index > cur.chapter_index
    if prev.in_world_date and cur.in_world_date:
        return _date_sort_key(prev.in_world_date) > _date_sort_key(
            cur.in_world_date
        )
    return False


def _find_cycles(by_id: dict[int, PlotEvent]) -> list[list[int]]:
    """Return the cycles formed by prev_event_id pointers.

    Each event has at most one outgoing pointer (its predecessor), so the
    residual graph after Kahn pruning is a set of disjoint simple cycles.
    """
    edges: dict[int, int] = {
        pe.id: pe.prev_event_id
        for pe in by_id.values()
        if pe.prev_event_id is not None and pe.prev_event_id in by_id
    }
    if not edges:
        return []

    # indegree over ALL events (roots with no pointer are also counted as
    # possible cycle targets when another event points to them).
    indegree = {eid: 0 for eid in by_id}
    for prev_id in edges.values():
        indegree[prev_id] += 1

    queue = deque(eid for eid in by_id if indegree[eid] == 0)
    removed: set[int] = set()
    while queue:
        eid = queue.popleft()
        removed.add(eid)
        if eid not in edges:
            continue
        prev_id = edges[eid]
        indegree[prev_id] -= 1
        if indegree[prev_id] == 0:
            queue.append(prev_id)

    cyclic = [eid for eid in edges if eid not in removed]
    if not cyclic:
        return []

    cycles: list[list[int]] = []
    seen: set[int] = set()
    for start in cyclic:
        if start in seen:
            continue
        chain: list[int] = []
        cur = start
        while cur not in seen:
            seen.add(cur)
            chain.append(cur)
            cur = edges[cur]
        idx = chain.index(cur)
        cycle = chain[idx:]
        # Normalize so each cycle starts at its smallest id.
        min_id = min(cycle)
        idx = cycle.index(min_id)
        cycles.append(cycle[idx:] + cycle[:idx])
    return cycles


def _topological_order(
    by_id: dict[int, PlotEvent], edges: list[TimelineEdge],
) -> list[int]:
    """Kahn topological sort over prev->cur edges.

    Events left over after pruning are in cycles; they are appended by id so
    the view still renders every event.
    """
    adj: dict[int, list[int]] = {eid: [] for eid in by_id}
    indegree = {eid: 0 for eid in by_id}
    for edge in edges:
        adj[edge.from_id].append(edge.to_id)
        indegree[edge.to_id] += 1

    queue = deque(sorted(eid for eid in by_id if indegree[eid] == 0))
    result: list[int] = []
    while queue:
        eid = queue.popleft()
        result.append(eid)
        for nxt in sorted(adj[eid]):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    result.extend(sorted(eid for eid in by_id if eid not in result))
    return result


def build_timeline_dag(events: list[PlotEvent]) -> TimelineDag:
    """Build nodes + edges from prev_event_id and surface structural warnings.

    Warnings produced:
      - predecessor: prev_event_id points to an event that does not exist
      - reverse_order: a causal predecessor is placed after its successor
        (by chapter_index or in_world_date)
      - cycle: the prev_event_id chain loops back on itself
    """
    by_id = {pe.id: pe for pe in events}
    ordered = sorted(events, key=_sort_key)
    order = {pe.id: i for i, pe in enumerate(ordered)}

    nodes = [
        TimelineNode(
            event_id=pe.id,
            event_type=pe.event_type,
            summary=pe.summary,
            chapter_id=pe.chapter_id,
            chapter_index=pe.chapter_index,
            in_world_date=pe.in_world_date,
            prev_event_id=pe.prev_event_id,
        )
        for pe in ordered
    ]

    edges: list[TimelineEdge] = []
    warnings: list[TimelineWarning] = []
    for pe in ordered:
        if pe.prev_event_id is None:
            continue
        prev = by_id.get(pe.prev_event_id)
        if prev is None:
            warnings.append(
                TimelineWarning(
                    kind=_WARN_PREDECESSOR, event_id=pe.id,
                    detail=f"事件 {pe.id} 引用的前置事件 {pe.prev_event_id} 不存在",
                )
            )
            continue
        edges.append(TimelineEdge(from_id=prev.id, to_id=pe.id))
        if _violates_causal_order(prev, pe):
            warnings.append(
                TimelineWarning(
                    kind=_WARN_REVERSE_ORDER, event_id=pe.id,
                    detail=(
                        f"事件 {pe.id} 的前置事件 {prev.id} 排在更后"
                        f"（章 {prev.chapter_index if prev.chapter_index is not None else '?'}"
                        f" 在 {pe.chapter_index if pe.chapter_index is not None else '?'} 之后）"
                    ),
                )
            )

    for cycle in _find_cycles(by_id):
        chain = " -> ".join(str(eid) for eid in cycle + [cycle[0]])
        warnings.append(
            TimelineWarning(
                kind=_WARN_CYCLE, event_id=cycle[0],
                detail=f"检测到事件环路: {chain}",
            )
        )

    return TimelineDag(
        nodes=nodes,
        edges=edges,
        warnings=warnings,
        topological_ids=_topological_order(by_id, edges),
    )


def _in_chapter(
    pe: PlotEvent, *, chapter_id: int | None, chapter_index: int,
) -> bool:
    """True when the event belongs to the chapter being written."""
    if chapter_id is not None and pe.chapter_id == chapter_id:
        return True
    return pe.chapter_index == chapter_index


async def validate_chapter_write(
    session: AsyncSession,
    *,
    novel_id: int,
    chapter_index: int,
    chapter_id: int | None = None,
) -> list[TimelineWarning]:
    """Real-time write-time check for the chapter being saved.

    Loads all of the novel's plot events, builds the DAG, and returns the
    warnings that touch this chapter: predecessor / reverse-order findings on
    events placed here (or whose predecessor is placed here), plus every
    cycle warning (a cycle is a structural defect regardless of chapter).
    """
    result = await session.execute(
        select(PlotEvent).where(PlotEvent.novel_id == novel_id)
    )
    events = list(result.scalars().all())
    dag = build_timeline_dag(events)
    by_id = {pe.id: pe for pe in events}

    relevant: list[TimelineWarning] = []
    for warning in dag.warnings:
        if warning.kind == _WARN_CYCLE:
            relevant.append(warning)
            continue
        event = by_id.get(warning.event_id)
        prev = by_id.get(event.prev_event_id) if event is not None else None
        if event is not None and _in_chapter(
            event, chapter_id=chapter_id, chapter_index=chapter_index,
        ):
            relevant.append(warning)
        elif prev is not None and _in_chapter(
            prev, chapter_id=chapter_id, chapter_index=chapter_index,
        ):
            relevant.append(warning)
    return relevant


async def get_timeline(session: AsyncSession, *, novel_id: int) -> TimelineDag:
    """Load the novel's plot events and build the timeline view."""
    result = await session.execute(
        select(PlotEvent).where(PlotEvent.novel_id == novel_id)
    )
    events = list(result.scalars().all())
    return build_timeline_dag(events)