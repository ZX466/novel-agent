import { describe, expect, it } from "vitest";
import { computeTimelineLayout } from "../TimelineGraph";
import type { TimelineResponse } from "@/lib/timeline";

/**
 * R10 布局 bug 回归: 37 个事件 0 边（prev_event_id 全空的真实数据）时,
 * 原型固定 H=300 把所有节点压进 ~220px → 卡片全部重叠。
 * H 必须随最高列节点数伸展,每节点 ≥40px。
 */

function makeData(
  nodes: Array<{ id: number; type?: string }>,
  edges: Array<[number, number]> = [],
  topo?: number[],
): Pick<TimelineResponse, "nodes" | "edges" | "topological_order"> {
  return {
    nodes: nodes.map((n) => ({
      event_id: n.id,
      event_type: n.type ?? "其他",
      summary: `事件${n.id}`,
      chapter_index: 0,
      in_world_date: null as string | null,
      chapter_id: null as number | null,
      prev_event_id: null as number | null,
    })) as TimelineResponse["nodes"],
    edges: edges.map(([f, t]) => ({ from_id: f, to_id: t })) as TimelineResponse["edges"],
    topological_order: topo ?? nodes.map((n) => n.id),
    warnings: [],
  } as never;
}

describe("computeTimelineLayout", () => {
  it("stretches H so 37 edgeless events stay readable (~38px rows, no overlap)", () => {
    const nodes = Array.from({ length: 37 }, (_, i) => ({ id: i + 1 }));
    const layout = computeTimelineLayout(makeData(nodes));
    expect(layout).not.toBeNull();
    // H grows beyond the prototype's 300 to fit the column.
    expect(layout!.H).toBeGreaterThan(300);
    // Consecutive y positions must be ≥ 35px apart (cards are 24px tall —
    // 35px spacing leaves an 11px gap; the old fixed H=300 gave ~6px).
    const ys = [...layout!.pos.values()].map((p) => p.y).sort((a, b) => a - b);
    for (let i = 1; i < ys.length; i++) {
      expect(ys[i] - ys[i - 1]).toBeGreaterThanOrEqual(34.9);
    }
  });

  it("keeps prototype base geometry for the demo-scale 8-node graph", () => {
    const nodes = Array.from({ length: 8 }, (_, i) => ({ id: i + 1 }));
    const layout = computeTimelineLayout(makeData(nodes));
    // 46 + 8*40 = 366 — MIN_ROW_PX governs even at demo scale (slightly
    // taller than the prototype's fixed 300, same visual language).
    expect(layout!.H).toBe(366);
  });

  it("layers chained events by topological depth (edges → columns)", () => {
    // 1 → 2 → 3: three layers, one node each.
    const nodes = [{ id: 1, type: "起" }, { id: 2, type: "承" }, { id: 3, type: "转" }];
    const layout = computeTimelineLayout(makeData(nodes, [[1, 2], [2, 3]]));
    expect(layout!.maxLayer).toBe(2);
    const p1 = layout!.pos.get(1)!;
    const p2 = layout!.pos.get(2)!;
    const p3 = layout!.pos.get(3)!;
    expect(p2.x).toBeGreaterThan(p1.x);
    expect(p3.x).toBeGreaterThan(p2.x);
    // Single-node columns use the base geometry (H stays 300).
    expect(layout!.H).toBe(300);
  });

  it("returns null for empty node list", () => {
    expect(computeTimelineLayout(makeData([]))).toBeNull();
  });
});
