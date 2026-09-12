"use client";
/**
 * TimelineGraph (R10) — layered causal DAG of plot events.
 *
 * OpenDesign prototype port: fixed 320×300 viewBox scaled to container
 * width (`.graph-svg` style `width:100%`), colW compressed by layer count,
 * 52×24 node cards, warn/sel coloring. Layering: x by topological depth
 * (longest path from sources), y within layer evenly spaced by index;
 * `in_world_date` shows under each node; backend warnings (predecessor /
 * reverse_order / cycle) render as a list above the graph.
 */
import { useEffect, useMemo, useState } from "react";

import {
  fetchTimeline,
  type TimelineResponse,
} from "@/lib/timeline";

const VIEW_W = 320;
const VIEW_H = 300;
const EDGE_ARROW = 1.4;

function isCausal(t: string): boolean {
  return t === "起" || t === "承" || t === "转" || t === "合" || t === "高潮";
}

export function TimelineGraph({ docId }: { docId: number }) {
  const [data, setData] = useState<TimelineResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);

  useEffect(() => {
    let alive = true;
    setError(null);
    setSelected(null);
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
    const layer = new Map<number, number>();
    for (const id of data.topological_order) {
      const ps = preds.get(id) ?? [];
      layer.set(id, ps.length === 0 ? 0 : Math.max(...ps.map((p) => (layer.get(p) ?? 0) + 1)));
    }
    let maxLayer = 0;
    for (const l of layer.values()) maxLayer = Math.max(maxLayer, l);
    const cols = new Map<number, typeof data.nodes>();
    for (const n of data.nodes) {
      const l = layer.get(n.event_id) ?? 0;
      if (!cols.has(l)) cols.set(l, []);
      cols.get(l)?.push(n);
    }
    // Prototype geometry: W=320 H=300, colW=(W-70)/(maxLayer+1), x=40+l*colW,
    // y=46+(i+1)*((H-80)/(len+1)) — compressed, container-scaled.
    const colW = (VIEW_W - 70) / Math.max(1, maxLayer + 1);
    const pos = new Map<number, { x: number; y: number }>();
    for (const [l, arr] of [...cols.entries()].sort((a, b) => a[0] - b[0])) {
      arr.forEach((n, i) => {
        pos.set(n.event_id, {
          x: 40 + l * colW,
          y: 46 + (i + 1) * ((VIEW_H - 80) / (arr.length + 1)),
        });
      });
    }
    return { pos, maxLayer };
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
  const warnIds = new Set(data.warnings.map((w) => w.event_id));
  const selNode = selected != null ? nodeById.get(selected) : undefined;

  return (
    <div className="flex flex-col gap-sp-2">
      <div className="flex items-center justify-between">
        <span className="text-[12px] font-semibold" style={{ color: "var(--fg)" }}>
          时间线因果 DAG
        </span>
        <span className="text-[11px]" style={{ color: "var(--muted)" }}>
          {data.nodes.length} 事件 · {data.edges.length} 边
          {data.warnings.length > 0 ? ` · ${data.warnings.length} 警告` : ""}
        </span>
      </div>

      {data.warnings.length > 0 && (
        <ul className="flex flex-col gap-sp-1">
          {data.warnings.map((w, i) => (
            <li
              key={i}
              className="px-sp-2 py-sp-1 rounded-sm text-[11px]"
              style={{ color: "var(--warn)", background: "oklch(0.74 0.10 85 / 0.08)" }}
            >
              [{w.kind === "reverse_order" ? "顺序倒置" : "前驱缺失"}] {w.detail}
            </li>
          ))}
        </ul>
      )}

      {layout && (
        <div
          className="rounded-md relative"
          style={{
            border: "1px solid var(--border-subtle)",
            background: "var(--surface-inset, var(--surface-2))",
            overflow: "hidden",
          }}
        >
          <svg
            viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
            className="block w-full h-auto"
            role="img"
            aria-label="时间线因果图"
          >
            <defs>
              <marker id="tl-arrow" viewBox="0 0 7 7" refX={6} refY={3.5} markerWidth={7} markerHeight={7} orient="auto">
                <path d="M0,0 L7,3.5 L0,7 z" fill="var(--border-hairline)" />
              </marker>
            </defs>
            {data.edges.map((e, i) => {
              const a = layout.pos.get(e.from_id);
              const b = layout.pos.get(e.to_id);
              if (!a || !b) return null;
              const mx = (a.x + b.x) / 2;
              return (
                <path
                  key={i}
                  d={`M${a.x} ${a.y} C${mx} ${a.y} ${mx} ${b.y} ${b.x} ${b.y}`}
                  fill="none"
                  stroke="var(--border-hairline)"
                  strokeWidth={EDGE_ARROW}
                  markerEnd="url(#tl-arrow)"
                />
              );
            })}
            {data.nodes.map((n) => {
              const p = layout.pos.get(n.event_id);
              if (!p) return null;
              const sel = selected === n.event_id;
              const warn = warnIds.has(n.event_id);
              return (
                <g
                  key={n.event_id}
                  style={{ cursor: "pointer" }}
                  onClick={() => setSelected(sel ? null : n.event_id)}
                >
                  <rect
                    x={p.x - 26}
                    y={p.y - 12}
                    width={52}
                    height={24}
                    rx={4}
                    fill={
                      sel
                        ? "var(--accent-bg)"
                        : warn
                          ? "color-mix(in oklch, var(--warn) 14%, transparent)"
                          : "var(--surface-2)"
                    }
                    stroke={
                      sel ? "var(--accent)" : warn ? "var(--warn)" : "var(--border)"
                    }
                  />
                  <text
                    x={p.x}
                    y={p.y + 4}
                    fontSize="9"
                    textAnchor="middle"
                    fill="var(--fg)"
                    fontWeight={600}
                  >
                    {n.event_type}
                  </text>
                  <text
                    x={p.x}
                    y={p.y + 24}
                    fontSize="8"
                    textAnchor="middle"
                    fill="var(--muted)"
                  >
                    {n.in_world_date || ""}
                  </text>
                </g>
              );
            })}
          </svg>
        </div>
      )}

      {/* Selected event detail card */}
      {selNode && (
        <div
          className="rounded-md px-sp-3 py-sp-2 text-[12px]"
          style={{
            border: "1px solid var(--border-subtle)",
            background: "var(--surface-2)",
            lineHeight: 1.6,
          }}
        >
          <div className="flex items-center justify-between gap-sp-2">
            <strong style={{ color: "var(--fg)" }}>{selNode.summary}</strong>
            <span className="text-[10px] shrink-0" style={{ color: "var(--muted)" }}>
              {selNode.event_type}
            </span>
          </div>
          <div style={{ marginTop: 4, color: "var(--fg-tertiary)" }}>
            世界内日期：{selNode.in_world_date || "—"} · 章节 {selNode.chapter_index ?? "—"}
          </div>
        </div>
      )}
    </div>
  );
}
