"use client";

/**
 * 全屏可视化页（R10-⑤）：人物关系图 / 时间线因果 DAG 的独立界面。
 *
 * 编辑器左栏的 200px 侧栏只适合快速预览；此页给图形完整宽度，SVG 的
 * viewBox 自适应缩放会自动放大（RelationshipGraph/TimelineGraph 内部
 * 均 width:100%）。数据由组件自己拉取（docId 驱动），无父级状态。
 */
import { useCallback, useState } from "react";
import { useParams, useSearchParams, useRouter } from "next/navigation";

import { RelationshipGraph } from "@/components/RelationshipGraph";
import { TimelineGraph } from "@/components/TimelineGraph";

type GraphTab = "graph" | "timeline";

const TABS: Array<{ key: GraphTab; label: string; title: string }> = [
  { key: "graph", label: "🕸 人物关系图", title: "角色关系力导向图" },
  { key: "timeline", label: "⏳ 时间线因果 DAG", title: "剧情事件因果图" },
];

export default function NovelGraphPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const router = useRouter();
  const docId = Number(params.id);
  // Editor sidebar jumps here with ?tab=timeline|graph (default graph).
  const [tab, setTab] = useState<GraphTab>(
    searchParams.get("tab") === "timeline" ? "timeline" : "graph",
  );

  const back = useCallback(() => {
    // 有历史则回编辑器，否则回作品列表。
    if (typeof window !== "undefined" && window.history.length > 1) {
      router.back();
    } else {
      router.push(`/novels/${docId}/editor`);
    }
  }, [router, docId]);

  if (!docId || isNaN(docId)) {
    return (
      <main className="flex flex-col items-center justify-center h-full gap-sp-4" style={{ background: "var(--bg)" }}>
        <p className="text-[14px]" style={{ color: "var(--danger)" }}>无效的作品链接</p>
        <button
          type="button"
          onClick={() => router.push("/novels")}
          className="px-sp-4 py-sp-2 rounded-sm text-[12px] font-medium border transition-colors"
          style={{ borderColor: "var(--border)", color: "var(--fg-secondary)" }}
        >
          返回作品列表
        </button>
      </main>
    );
  }

  return (
    <main className="flex flex-col h-full overflow-hidden" style={{ background: "var(--bg)" }}>
      {/* Header: back + title + tab switch */}
      <div
        className="flex items-center gap-sp-3 px-sp-5 py-sp-3 border-b shrink-0"
        style={{ borderColor: "var(--border-subtle)", background: "var(--surface)" }}
      >
        <button
          type="button"
          onClick={back}
          className="w-7 h-7 flex items-center justify-center rounded-sm transition-colors shrink-0"
          style={{ color: "var(--muted)" }}
          title="返回编辑器"
          aria-label="返回编辑器"
          onMouseEnter={(e) => {
            e.currentTarget.style.background = "var(--surface-2)";
            e.currentTarget.style.color = "var(--fg)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = "transparent";
            e.currentTarget.style.color = "var(--muted)";
          }}
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="19" y1="12" x2="5" y2="12" />
            <polyline points="12 19 5 12 12 5" />
          </svg>
        </button>
        <h1 className="font-display text-[15px] font-semibold shrink-0" style={{ color: "var(--fg)" }}>
          可视化
        </h1>
        <div
          className="flex rounded-sm overflow-hidden border text-[12px] shrink-0"
          style={{ borderColor: "var(--border-hairline)" }}
        >
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              title={t.title}
              className="px-sp-4 py-sp-1.5 transition-colors"
              style={{
                background: tab === t.key ? "var(--accent-bg)" : "transparent",
                color: tab === t.key ? "var(--accent)" : "var(--muted)",
                fontWeight: tab === t.key ? 600 : 400,
              }}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Full-width graph body */}
      <div className="flex-1 overflow-y-auto min-h-0 px-sp-8 py-sp-6">
        <div className="mx-auto" style={{ maxWidth: 980 }}>
          {tab === "graph" && <RelationshipGraph docId={docId} />}
          {tab === "timeline" && <TimelineGraph docId={docId} />}
        </div>
      </div>
    </main>
  );
}
