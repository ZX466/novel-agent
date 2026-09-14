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
  it("stretches H so 37 edgeless events keep dot+label rows readable", () => {
    const nodes = Array.from({ length: 37 }, (_, i) => ({ id: i + 1 }));
    const layout = computeTimelineLayout(makeData(nodes));
    expect(layout).not.toBeNull();
    expect(layout!.H).toBeGreaterThan(300);
    // Dots are 7-9px; ≥20px spacing keeps labels from colliding (old fixed
    // H=300 gave ~6px).
    const ys = [...layout!.pos.values()].map((p) => p.y).sort((a, b) => a - b);
    for (let i = 1; i < ys.length; i++) {
      expect(ys[i] - ys[i - 1]).toBeGreaterThanOrEqual(19.9);
    }
  });

  it("stretches W when chains create columns so right-side labels fit", () => {
    // 5-node chain → 5 layers; colW floors at 160 so labels don't clip.
    const nodes = [1, 2, 3, 4, 5].map((id) => ({ id }));
    const edges: Array<[number, number]> = [[1, 2], [2, 3], [3, 4], [4, 5]];
    const layout = computeTimelineLayout(makeData(nodes, edges));
    expect(layout!.maxLayer).toBe(4);
    expect(layout!.W).toBeGreaterThan(320);
    // Ascending x per layer.
    const xs = [1, 2, 3, 4, 5].map((id) => layout!.pos.get(id)!.x);
    for (let i = 1; i < xs.length; i++) expect(xs[i]).toBeGreaterThan(xs[i - 1]);
  });

  it("single-layer small graph stays at base geometry", () => {
    const nodes = Array.from({ length: 8 }, (_, i) => ({ id: i + 1 }));
    const layout = computeTimelineLayout(makeData(nodes));
    // 09-14: base scaled 3× (960×900) to match the ~916px container —
    // the old 320×300 viewBox blew up ~2.9× via width:100% ("字太大").
    expect(layout!.H).toBe(900);
    // One layer: colW = (960-80)/1 = 880, W = 40+880+40 = 960.
    expect(layout!.W).toBe(960);
  });

  it("returns null for empty node list", () => {
    expect(computeTimelineLayout(makeData([]))).toBeNull();
  });
});
