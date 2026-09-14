/**
 * 09-14 全屏可视化页修复(用户报告):
 * ① 时间线图"界面太小、字太大"——根因是 SVG viewBox 基准过小
 *   (320×300)却 width:100% 拉伸到 ~916px 容器,整图被放大 ~2.9 倍,
 *   8.5px 字号渲染成 ~25px。修复:基准放大约 3 倍(960×900),同一
 *   容器下缩放比 ≈1,字号回归设计值。
 * ② 容器 maxWidth 980 锁死全屏页宽度——放宽到 1400,大屏占满更多。
 */
import { describe, expect, it } from "vitest";
import { computeTimelineLayout, TIMELINE_VIEW_W } from "../TimelineGraph";
import type { TimelineResponse } from "@/lib/timeline";

function makeData(
  nodes: Array<{ id: number }>,
  edges: Array<[number, number]> = [],
): Pick<TimelineResponse, "nodes" | "edges" | "topological_order"> {
  return {
    nodes: nodes.map((n) => ({
      event_id: n.id,
      event_type: "其他",
      summary: `事件${n.id}`,
      chapter_index: 0,
      in_world_date: null as string | null,
      chapter_id: null as number | null,
      prev_event_id: null as number | null,
    })) as TimelineResponse["nodes"],
    edges: edges.map(([f, t]) => ({ from_id: f, to_id: t })) as TimelineResponse["edges"],
    topological_order: nodes.map((n) => n.id),
    warnings: [],
  } as never;
}

describe("09-14 时间线渲染尺寸", () => {
  it("viewBox 基准宽 ≥900(与 ~916px 容器同量级,消除 ~3x 放大)", () => {
    expect(TIMELINE_VIEW_W).toBeGreaterThanOrEqual(900);
  });

  it("0 边 43 事件在全尺寸基准下 H 随节点数伸展且行距足够", () => {
    const nodes = Array.from({ length: 43 }, (_, i) => ({ id: i + 1 }));
    const layout = computeTimelineLayout(makeData(nodes));
    expect(layout).not.toBeNull();
    expect(layout!.H).toBeGreaterThan(800); // 43 × 22px 行距
    const ys = [...layout!.pos.values()].map((p) => p.y).sort((a, b) => a - b);
    for (let i = 1; i < ys.length; i++) {
      expect(ys[i] - ys[i - 1]).toBeGreaterThanOrEqual(19.9);
    }
  });

  it("单列小图保持基础几何", () => {
    const nodes = Array.from({ length: 8 }, (_, i) => ({ id: i + 1 }));
    const layout = computeTimelineLayout(makeData(nodes));
    expect(layout!.H).toBe(900);
  });
});
