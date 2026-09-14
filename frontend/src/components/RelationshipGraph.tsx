"use client";
/**
 * RelationshipGraph (R10) — force-directed character relationship graph.
 *
 * Renders RelationshipGraph data as an SVG: nodes positioned by a
 * deterministic force simulation (repulsion + link spring + centering,
 * ported from the OpenDesign prototype), edges weighted by `strength`.
 * Interactions:
 *  - click node  → select, show detail + relation list
 *  - click edge  → select, edit relation (PUT) or delete (DELETE)
 *  - drag node   → reposition (persisted layout is local-only; backend
 *                  stores the graph, not coordinates)
 *  - 一键导入    → POST /import from the novel's outline (backend derives
 *                  pairs; import result surfaced with created/updated/skipped)
 * 409 from PUT/DELETE surfaces as a toast (duplicate relation edits are the
 * expected collision — R9-③ P1-A dedup contract).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  deleteRelationship,
  fetchRelationshipGraph,
  importRelationships,
  upsertRelationship,
  type RelationshipGraph as GraphData,
  type RelationshipGraphEdge,
  type RelationshipGraphNode,
  type RelationshipImportItem,
} from "@/lib/character-relationships";

// 09-14: 基准从 320×300 放大 3 倍——与 TimelineGraph 同理,原基准配合
// width:100% 渲染进 ~1376px 容器时整图放大 ~4.3 倍(用户报告"字太大")。
// 力导向常数(rep 4200/d²、spring d-78)按 W 无量纲耦合,等比放大不变。
const W = 960;
const H = 900;
const ITERATIONS = 260;

function roleColor(role: string): string {
  if (role === "主角") return "var(--accent)";
  if (role === "反派") return "var(--danger)";
  return "var(--fg-tertiary)";
}

/** R10 dot-node scale: small dots + names beside them hold up at any cast
 *  size (the prototype's 20/24px circles swallowed a dense graph). */
function nodeRadius(role: string): number {
  return role === "主角" ? 7 : 5.5;
}

interface Pt {
  x: number;
  y: number;
}

/** Deterministic force layout — same constants as the prototype
 *  (W=320 H=300, rep 4200/d², 260 iters, spring (d-78)*0.015). */
function layoutGraph(nodes: RelationshipGraphNode[], edges: RelationshipGraphEdge[]): Map<number, Pt> {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const pts = new Map<number, Pt>();
  nodes.forEach((n, i) => {
    const angle = (2 * Math.PI * i) / Math.max(1, nodes.length);
    pts.set(n.id, {
      x: W / 2 + Math.cos(angle) * Math.min(W, H) * 0.32,
      y: H / 2 + Math.sin(angle) * Math.min(W, H) * 0.32,
    });
  });
  for (let iter = 0; iter < ITERATIONS; iter++) {
    const vel = new Map<number, Pt>([...pts.entries()].map(([id, p]) => [id, { x: 0, y: 0 }]));
    // node-node repulsion
    const arr = [...pts.entries()];
    for (let a = 0; a < arr.length; a++) {
      for (let b = a + 1; b < arr.length; b++) {
        const [ida, pa] = arr[a];
        const [idb, pb] = arr[b];
        const dx = pb.x - pa.x;
        const dy = pb.y - pa.y;
        const d2 = dx * dx + dy * dy || 0.01;
        const d = Math.sqrt(d2);
        const f = 4200 / d2;
        (vel.get(ida) as Pt).x -= (dx / d) * f;
        (vel.get(ida) as Pt).y -= (dy / d) * f;
        (vel.get(idb) as Pt).x += (dx / d) * f;
        (vel.get(idb) as Pt).y += (dy / d) * f;
      }
    }
    // link spring
    for (const e of edges) {
      const a = pts.get(e.subject_id);
      const b = pts.get(e.object_id);
      if (!a || !b) continue;
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const d = Math.hypot(dx, dy) || 1;
      const k = (d - 78) * 0.015;
      (vel.get(e.subject_id) as Pt).x += (dx / d) * k;
      (vel.get(e.subject_id) as Pt).y += (dy / d) * k;
      (vel.get(e.object_id) as Pt).x -= (dx / d) * k;
      (vel.get(e.object_id) as Pt).y -= (dy / d) * k;
    }
    // centering + integrate + clamp
    for (const [id, p] of pts) {
      const v = vel.get(id) as Pt;
      v.x += (W / 2 - p.x) * 0.004;
      v.y += (H / 2 - p.y) * 0.004;
      v.x *= 0.82;
      v.y *= 0.82;
      p.x = Math.max(16, Math.min(W - 90, p.x + v.x)); // right margin reserves label room
      p.y = Math.max(30, Math.min(H - 30, p.y + v.y));
    }
  }
  return pts;
}

export function RelationshipGraph({ docId }: { docId: number }) {
  const [graph, setGraph] = useState<GraphData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [selectedEdge, setSelectedEdge] = useState<number | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  // Local coordinate overrides (node drag) — layout is view-local.
  const [overrides, setOverrides] = useState<Map<number, Pt>>(new Map());
  // Manual import editor: pairs added here are batch-upserted via /import
  // (unknown names are skipped server-side and counted).
  const [draftItems, setDraftItems] = useState<RelationshipImportItem[]>([]);
  const [draftSubject, setDraftSubject] = useState("");
  const [draftObject, setDraftObject] = useState("");
  const [draftRel, setDraftRel] = useState("");
  const svgRef = useRef<SVGSVGElement>(null);

  const reload = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      setGraph(await fetchRelationshipGraph(docId));
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载关系图失败");
    } finally {
      setBusy(false);
    }
  }, [docId]);

  useEffect(() => {
    void reload();
    setOverrides(new Map());
    setSelectedEdge(null);
  }, [reload]);

  const positions = useMemo(() => {
    if (!graph) return new Map<number, Pt>();
    const base = layoutGraph(graph.nodes, graph.edges);
    overrides.forEach((p, id) => base.set(id, p));
    return base;
  }, [graph, overrides]);

  const showToast = useCallback((msg: string) => {
    setToast(msg);
    window.setTimeout(() => setToast(null), 3500);
  }, []);

  const handleNodeDown = (e: React.PointerEvent, id: number) => {
    e.preventDefault();
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const scaleX = W / rect.width;
    const scaleY = H / rect.height;
    const move = (ev: PointerEvent) => {
      const x = Math.max(16, Math.min(W - 90, (ev.clientX - rect.left) * scaleX));
      const y = Math.max(30, Math.min(H - 30, (ev.clientY - rect.top) * scaleY));
      setOverrides((prev) => new Map(prev).set(id, { x, y }));
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  const handleDelete = async (edge: RelationshipGraphEdge) => {
    setBusy(true);
    try {
      await deleteRelationship(docId, edge.subject_id, edge.object_id);
      showToast("关系已删除");
      setSelectedEdge(null);
      await reload();
    } catch (err) {
      showToast(err instanceof Error ? err.message : "删除失败");
    } finally {
      setBusy(false);
    }
  };

  const handleStrength = async (edge: RelationshipGraphEdge, strength: number) => {
    setBusy(true);
    try {
      await upsertRelationship(docId, edge.subject_id, edge.object_id, {
        relation_type: edge.relation_type,
        description: edge.description,
        strength,
      });
      showToast(`关系强度已更新为 ${strength}`);
      await reload();
    } catch (err) {
      // 409 = concurrent edit / duplicate — surface server text verbatim.
      showToast(err instanceof Error ? err.message : "更新失败");
    } finally {
      setBusy(false);
    }
  };

  const handleImport = async () => {
    setBusy(true);
    try {
      const r = await importRelationships(docId, draftItems);
      showToast(`导入完成：新建 ${r.created}，更新 ${r.updated}，跳过 ${r.skipped}`);
      await reload();
    } catch (err) {
      showToast(err instanceof Error ? err.message : "导入失败");
    } finally {
      setBusy(false);
    }
  };

  if (error) {
    return (
      <div className="px-sp-3 py-sp-3 text-[12px]" style={{ color: "var(--danger)" }}>
        {error}
      </div>
    );
  }
  if (!graph) {
    return (
      <div className="px-sp-3 py-sp-3 text-[12px]" style={{ color: "var(--muted)" }}>
        加载中…
      </div>
    );
  }
  if (graph.nodes.length === 0) {
    return (
      <div className="px-sp-3 py-sp-4 text-[12px]" style={{ color: "var(--muted)" }}>
        还没有人物。先在「人物」面板添加角色，或从大纲一键提取。
      </div>
    );
  }

  const selEdge = selectedEdge != null ? graph.edges[selectedEdge] : null;
  const selNode = selEdge
    ? graph.nodes.find((n) => n.id === selEdge.subject_id)
    : null;

  return (
    <div className="flex flex-col gap-sp-2">
      <div className="flex items-center justify-between gap-sp-2">
        <span className="text-[12px] font-semibold" style={{ color: "var(--fg)" }}>
          人物关系图（{graph.nodes.length} 人 / {graph.edges.length} 条关系）
        </span>
        <button
          type="button"
          disabled={busy}
          onClick={handleImport}
          className="px-sp-2 py-sp-1 rounded-sm text-[11px] font-medium disabled:opacity-50"
          style={{ background: "var(--accent-bg)", color: "var(--accent)" }}
        >
          一键导入
        </button>
      </div>

      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        className="block w-full h-auto rounded-sm"
        role="img"
        aria-label="人物关系图。可拖动节点。"
        style={{ maxWidth: W, background: "var(--surface-inset, var(--surface-2))", border: "1px solid var(--border-subtle)", touchAction: "none" }}
      >
        {graph.edges.map((e, i) => {
          const a = positions.get(e.subject_id);
          const b = positions.get(e.object_id);
          if (!a || !b) return null;
          const sel = selectedEdge === i;
          return (
            <g key={`${e.subject_id}-${e.object_id}`} onClick={() => setSelectedEdge(i)}>
              <line
                x1={a.x}
                y1={a.y}
                x2={b.x}
                y2={b.y}
                stroke={sel ? "var(--accent)" : "var(--border-hairline)"}
                strokeWidth={1 + e.strength * 0.32}
                strokeOpacity={sel ? 0.95 : 0.55}
              />
              <text
                x={(a.x + b.x) / 2}
                y={(a.y + b.y) / 2 - 3}
                fontSize="9"
                textAnchor="middle"
                fill="var(--muted)"
              >
                {e.relation_type.slice(0, 8)}
              </text>
            </g>
          );
        })}
        {graph.nodes.map((n) => {
          const p = positions.get(n.id);
          if (!p) return null;
          const r = nodeRadius(n.role);
          return (
            <g
              key={n.id}
              style={{ cursor: "grab" }}
              onPointerDown={(ev) => handleNodeDown(ev, n.id)}
            >
              {/* Dot node + full name beside it — no two-char truncation,
                  no giant circles: scales to any cast size (R10). */}
              <circle
                cx={p.x}
                cy={p.y}
                r={r}
                fill={roleColor(n.role)}
                fillOpacity={0.25}
                stroke={roleColor(n.role)}
                strokeWidth={n.role === "主角" ? 2 : 1.3}
              />
              <text
                x={p.x + r + 5}
                y={p.y + 3.5}
                fontSize="8.5"
                fill="var(--fg)"
                fontWeight={n.role === "主角" ? 650 : 400}
                style={{ pointerEvents: "none" }}
              >
                {n.name}
              </text>
            </g>
          );
        })}
      </svg>

      {selEdge && (
        <div
          className="px-sp-3 py-sp-2 rounded-sm text-[12px] flex flex-col gap-sp-2"
          style={{ background: "var(--surface-2)", border: "1px solid var(--border-subtle)" }}
        >
          <div className="flex items-center justify-between">
            <span style={{ color: "var(--fg)" }}>
              {graph.nodes.find((n) => n.id === selEdge.subject_id)?.name ?? "?"}
              <span style={{ color: "var(--muted)" }}> → {selEdge.relation_type || "关系"} → </span>
              {graph.nodes.find((n) => n.id === selEdge.object_id)?.name ?? "?"}
            </span>
            <button
              type="button"
              disabled={busy}
              onClick={() => handleDelete(selEdge)}
              className="text-[11px] px-sp-2 py-px rounded-sm disabled:opacity-50"
              style={{ color: "var(--danger)", border: "1px solid var(--danger)" }}
            >
              删除
            </button>
          </div>
          <div className="flex items-center gap-sp-2">
            <span style={{ color: "var(--fg-tertiary)" }}>强度</span>
            {[1, 3, 5, 7, 9].map((s) => (
              <button
                key={s}
                type="button"
                disabled={busy}
                onClick={() => handleStrength(selEdge, s)}
                className="w-6 h-6 rounded-sm text-[11px] disabled:opacity-50"
                style={
                  selEdge.strength === s
                    ? { background: "var(--accent)", color: "white" }
                    : { border: "1px solid var(--border-subtle)", color: "var(--fg-secondary)" }
                }
              >
                {s}
              </button>
            ))}
          </div>
          {selNode && selEdge.description && (
            <div style={{ color: "var(--fg-tertiary)" }}>{selEdge.description}</div>
          )}
        </div>
      )}

      {toast && (
        <div
          className="px-sp-3 py-sp-2 rounded-sm text-[12px]"
          style={{ background: "var(--surface-2)", border: "1px solid var(--accent)", color: "var(--fg)" }}
          role="status"
        >
          {toast}
        </div>
      )}

      {/* Manual import: batch upsert by character name (unknown → skipped). */}
      <details className="text-[12px]" style={{ color: "var(--fg-secondary)" }}>
        <summary className="cursor-pointer select-none" style={{ color: "var(--muted)" }}>
          按名字添加关系（批量导入）
        </summary>
        <div className="flex flex-col gap-sp-2 pt-sp-2">
          {draftItems.length > 0 && (
            <ul className="flex flex-col gap-1">
              {draftItems.map((it, i) => (
                <li key={i} className="flex items-center justify-between gap-sp-2">
                  <span>
                    {it.subject_name} → {it.relation_type || "关系"} → {it.object_name}
                  </span>
                  <button
                    type="button"
                    onClick={() => setDraftItems((prev) => prev.filter((_, j) => j !== i))}
                    className="text-[11px]"
                    style={{ color: "var(--danger)" }}
                  >
                    移除
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div className="flex items-center gap-sp-2">
            <input
              value={draftSubject}
              onChange={(e) => setDraftSubject(e.target.value)}
              placeholder="人物A（须已存在）"
              className="flex-1 px-sp-2 py-sp-1 rounded-sm text-[12px]"
              style={{ background: "var(--surface)", border: "1px solid var(--border-subtle)", color: "var(--fg)" }}
            />
            <input
              value={draftRel}
              onChange={(e) => setDraftRel(e.target.value)}
              placeholder="关系（如 师徒）"
              className="w-28 px-sp-2 py-sp-1 rounded-sm text-[12px]"
              style={{ background: "var(--surface)", border: "1px solid var(--border-subtle)", color: "var(--fg)" }}
            />
            <input
              value={draftObject}
              onChange={(e) => setDraftObject(e.target.value)}
              placeholder="人物B（须已存在）"
              className="flex-1 px-sp-2 py-sp-1 rounded-sm text-[12px]"
              style={{ background: "var(--surface)", border: "1px solid var(--border-subtle)", color: "var(--fg)" }}
            />
            <button
              type="button"
              disabled={!draftSubject.trim() || !draftObject.trim()}
              onClick={() => {
                setDraftItems((prev) => [
                  ...prev,
                  { subject_name: draftSubject.trim(), object_name: draftObject.trim(), relation_type: draftRel.trim() },
                ]);
                setDraftSubject("");
                setDraftObject("");
                setDraftRel("");
              }}
              className="px-sp-2 py-sp-1 rounded-sm text-[11px] disabled:opacity-50"
              style={{ border: "1px solid var(--border-subtle)", color: "var(--fg-secondary)" }}
            >
              添加
            </button>
            {draftItems.length > 0 && (
              <button
                type="button"
                disabled={busy}
                onClick={handleImport}
                className="px-sp-2 py-sp-1 rounded-sm text-[11px] font-medium disabled:opacity-50"
                style={{ background: "var(--accent)", color: "white" }}
              >
                导入 {draftItems.length} 条
              </button>
            )}
          </div>
        </div>
      </details>
    </div>
  );
}
