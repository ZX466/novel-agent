"use client";
/**
 * ConsistencyPanel (R10) — setting-consistency sentinel UI (R5-3).
 *
 * Runs the numeric-deterministic check (POST /consistency/check) against
 * the current chapter draft or pasted text, shows verdicts with evidence
 * snippets, and keeps a history of persisted checks (GET /consistency/checks).
 */
import { useCallback, useEffect, useState } from "react";

import {
  listConsistencyChecks,
  runConsistencyCheck,
  type ConsistencyCheckItem,
} from "@/lib/consistency";

function verdictColor(verdict: string): string {
  const v = verdict.toLowerCase();
  if (v.includes("pass") || v.includes("一致") || v === "ok") return "var(--success)";
  if (v.includes("fail") || v.includes("conflict") || v.includes("冲突")) return "var(--danger)";
  return "var(--warn)";
}

function row(item: ConsistencyCheckItem) {
  return (
    <div key={item.id} className="consistency-row">
      <div className="cr-head">
        <span className="text-[12px] font-semibold" style={{ color: "var(--fg)" }}>
          {item.target_name}
          <span className="text-[10px] ml-sp-2" style={{ color: "var(--muted)" }}>
            {item.target_type}#{item.target_id}
          </span>
        </span>
        <span className="text-[11px] font-medium" style={{ color: verdictColor(item.verdict) }}>
          {item.verdict}
        </span>
      </div>
      <div className="cr-detail">{item.detail}</div>
      {item.evidence_snippet && (
        <div className="cr-evidence">{item.evidence_snippet}</div>
      )}
    </div>
  );
}

export function ConsistencyPanel({
  docId,
  chapterId,
  chapterText,
}: {
  docId: number;
  chapterId: number | null;
  chapterText: string;
}) {
  const [items, setItems] = useState<ConsistencyCheckItem[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ranOnce, setRanOnce] = useState(false);

  const loadHistory = useCallback(async () => {
    try {
      const r = await listConsistencyChecks(docId);
      setItems(r.items);
    } catch (e) {
      // history load failure is non-fatal — the check itself still works
      setError(e instanceof Error ? e.message : "加载历史检查失败");
    }
  }, [docId]);

  useEffect(() => {
    void loadHistory();
  }, [loadHistory]);

  // A check needs a draft: the stored chapter (chapterId) or editor text.
  // Without either the backend 422s (「需要 chapter_id 或非空 content_text」),
  // which used to surface as a bare "请求失败 (422)".
  const hasDraft = chapterId != null || chapterText.trim().length > 0;

  const run = async () => {
    if (!hasDraft) {
      setError("没有可检查的内容——请先选择章节或在编辑器输入文本");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const req = chapterText.trim()
        ? { chapter_id: chapterId, content_text: chapterText.slice(0, 200_000) }
        : { chapter_id: chapterId };
      const r = await runConsistencyCheck(docId, req);
      setItems(r.items);
      setRanOnce(true);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "检查失败";
      // 422 = the request carried no scannable source; say why, not the code.
      setError(
        msg.includes("422")
          ? "没有可检查的内容——请先选择章节或输入文本后重试"
          : msg,
      );
    } finally {
      setBusy(false);
    }
  };

  const conflicts = (items ?? []).filter((i) => {
    const v = i.verdict.toLowerCase();
    return v.includes("fail") || v.includes("conflict") || v.includes("冲突");
  }).length;

  return (
    <div className="flex flex-col gap-sp-2 px-sp-3 py-sp-2">
      <div className="flex items-center justify-between">
        <span className="text-[12px] font-semibold" style={{ color: "var(--fg)" }}>
          设定一致性哨兵
          {ranOnce && items && (
            <span className="ml-sp-2 text-[11px]" style={{ color: conflicts > 0 ? "var(--danger)" : "var(--success)" }}>
              {conflicts > 0 ? `${conflicts} 处冲突` : "全部一致"}
            </span>
          )}
        </span>
        <button
          type="button"
          disabled={busy || !hasDraft}
          onClick={run}
          className="px-sp-2 py-sp-1 rounded-sm text-[11px] font-medium disabled:opacity-50"
          style={{ background: "var(--accent-bg)", color: "var(--accent)" }}
          title={hasDraft ? undefined : "请先选择章节或在编辑器输入文本"}
        >
          {ranOnce ? "重新检查" : "开始检查"}
        </button>
      </div>

      {busy && (
        <div className="text-[11px]" style={{ color: "var(--muted)" }}>
          正在比对角色历史设定…
        </div>
      )}
      {error && (
        <div className="text-[11px]" style={{ color: "var(--danger)" }}>
          {error}
        </div>
      )}

      {!busy && !ranOnce && items && items.length === 0 && (
        <div className="text-[11px]" style={{ color: "var(--muted)" }}>
          尚无检查记录。点「开始检查」将当前章节与角色设定做数值比对（出场次数、年龄、境界等）。
        </div>
      )}

      {items && items.length > 0 && items.map(row)}
    </div>
  );
}
