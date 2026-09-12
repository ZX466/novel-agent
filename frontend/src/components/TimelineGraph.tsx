"use client";
/**
 * TimelineGraph (R10) — layered causal DAG of plot events.
 *
 * Layering: x by topological depth (longest path from sources), y within
 * layer by world date then insertion order — mirrors the OpenDesign
 * prototype's deterministic layout. `in_world_date` shows under each node;
 * backend warnings (predecessor / reverse_order / cycle) render as a list
 * above the graph.
 */
import { useEffect, useMemo, useState } from "react";

import {
  fetchTimeline,
  type TimelineResponse,
} from "@/lib/timeline";

const NODE_W = 108;
const NODE_H = 30;
const GAP_X = 52;
const GAP_Y = 18;

function isCausal(t: string): boolean {
  return t === "起" || t === "承" || t === "转" || t === "合" || t === "高潮";
}

export function TimelineGraph({ docId }: { docId: number }) {
  const [data, setData] = useState<TimelineResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setError(null);
    fetchTimeline(docId)
      .then((r) => {
        if (alive) setData(r);
      })
      .catch((e: unknown) => {
        if (alive) setError(e instanceof Error ? e.message : "加载时间线失败");
      });
    return () => {
      alive = false;
    };
  }, [docId]);

  const layout = useMemo(() => {
    if (!data || data.nodes.length === 0) return null;
    const nodeById = new Map(data.nodes.map((n) => [n.event_id, n]));
    const preds = new Map<number, number[]>();
    for (const n of data.nodes) preds.set(n.event_id, []);
    for (const e of data.edges) {
      if (nodeById.has(e.from_id) && nodeById.has(e.to_id)) {
        preds.get(e.to_id)?.push(e.from_id);
      }
    }
    // longest-path layering over topological order
    const depth = new Map<number, number>();
    for (const id of data.topological_order) {
      const ps = preds.get(id) ?? [];
      depth.set(id, ps.length === 0 ? 0 : Math.max(...ps.map((p) => (depth.get(p) ?? 0) + 1)));
    }
    const byLayer = new Map<number, typeof data.nodes>();
    for (const n of data.nodes) {
      const layer = depth.get(n.event_id) ?? 0;
      if (!byLayer.has(layer)) byLayer.set(layer, []);
      byLayer.get(layer)?.push(n);
    }
    const pos = new Map<number, { x: number; y: number }>();
    let maxRows = 0;
    for (const [layer, nodes] of [...byLayer.entries()].sort((a, b) => a[0] - b[0])) {
      nodes.sort((a, b) => (a.in_world_date ?? "").localeCompare(b.in_world_date ?? ""));
      maxRows = Math.max(maxRows, nodes.length);
      nodes.forEach((n, i) => {
        pos.set(n.event_id, {
          x: 16 + layer * (NODE_W + GAP_X),
          y: 16 + i * (NODE_H + GAP_Y),
        });
      });
    }
    const width = 16 + ((byLayer.size || 1) * (NODE_W + GAP_X));
    const height = 16 + maxRows * (NODE_H + GAP_Y);
    return { pos, width, height };
  }, [data]);

  if (error) {
    return (
      <div className="px-sp-3 py-sp-3 text-[12px]" style={{ color: "var(--danger)" }}>
        {error}
      </div>
    );
  }
  if (!data) {
    return (
      <div className="px-sp-3 py-sp-3 text-[12px]" style={{ color: "var(--muted)" }}>
        加载中…
      </div>
    );
  }
  if (data.nodes.length === 0) {
    return (
      <div className="px-sp-3 py-sp-4 text-[12px]" style={{ color: "var(--muted)" }}>
        还没有剧情事件。在「剧情」面板添加事件后，这里会自动生成因果图谱。
      </div>
    );
  }

  const nodeById = new Map(data.nodes.map((n) => [n.event_id, n]));

  return (
    <div className="flex flex-col gap-sp-2">
      <div className="flex items-center justify-between">
        <span className="text-[12px] font-semibold" style={{ color: "var(--fg)" }}>
          时间线（{data.nodes.length} 事件 / {data.edges.length} 因果边）
        </span>
        {data.warnings.length > 0 && (
          <span className="text-[11px]" style={{ color: "var(--warn)" }}>
            {data.warnings.length} 条冲突警告
          </span>
        )}
      </div>

      {data.warnings.length > 0 && (
        <ul className="flex flex-col gap-sp-1">
          {data.warnings.map((w, i) => (
            <li
              key={i}
              className="px-sp-2 py-sp-1 rounded-sm text-[11px]"
              style={{ color: "var(--warn)", background: "oklch(0.74 0.10 85 / 0.08)" }}
            >
              [{w.kind}] {w.detail}
            </li>
          ))}
        </ul>
      )}

      {layout && (
        <div className="overflow-x-auto">
          <svg
            viewBox={`0 0 ${layout.width} ${layout.height}`}
            width={Math.max(layout.width, 640)}
            className="rounded-sm"
            style={{ background: "var(--surface-2)", border: "1px solid var(--border-subtle)" }}
          >
            {data.edges.map((e, i) => {
              const a = layout.pos.get(e.from_id);
              const b = layout.pos.get(e.to_id);
              if (!a || !b) return null;
              const x1 = a.x + NODE_W;
              const y1 = a.y + NODE_H / 2;
              const x2 = b.x;
              const y2 = b.y + NODE_H / 2;
              const mx = (x1 + x2) / 2;
              return (
                <path
                  key={i}
                  d={`M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`}
                  fill="none"
                  stroke="var(--border-hairline)"
                  strokeWidth={1.4}
                  strokeOpacity={0.7}
                  markerEnd="url(#tl-arrow)"
                />
              );
            })}
            <defs>
              <marker id="tl-arrow" viewBox="0 0 8 8" refX={7} refY={4} markerWidth={7} markerHeight={7} orient="auto">
                <path d="M0,0 L8,4 L0,8 z" fill="var(--border-hairline)" />
              </marker>
            </defs>
            {data.nodes.map((n) => {
              const p = layout.pos.get(n.event_id);
              if (!p) return null;
              const causal = isCausal(n.event_type);
              return (
                <g key={n.event_id}>
                  <rect
                    x={p.x}
                    y={p.y}
                    width={NODE_W}
                    height={NODE_H}
                    rx={6}
                    fill="var(--surface)"
                    stroke={causal ? "var(--accent)" : "var(--border-hairline)"}
                    strokeWidth={causal ? 1.6 : 1}
                  />
                  <text x={p.x + 8} y={p.y + 14} fontSize="10" fill="var(--fg)" fontWeight={600}>
                    {n.event_type}
                    {n.in_world_date ? ` · ${n.in_world_date}` : ""}
                  </text>
                  <text x={p.x + 8} y={p.y + 25} fontSize="9" fill="var(--fg-tertiary)">
                    {n.summary.length > 16 ? `${n.summary.slice(0, 16)}…` : n.summary}
                  </text>
                </g>
              );
            })}
          </svg>
        </div>
      )}

      {nodeById.size === 0 && null}
    </div>
  );
}
