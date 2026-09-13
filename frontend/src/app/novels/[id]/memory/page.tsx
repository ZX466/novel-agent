"use client";

/**
 * 记忆库（R10-⑥）：RAG 检索的全部原料（章节/人物/世界观/剧情事件/
 * 人物关系/知识文档）一处看全、搜索、删除；知识文档在此上传（文件或
 * 粘贴文本）。条目的精细编辑仍在编辑器各面板与关系图页完成。
 */
import { useCallback } from "react";
import { useParams, useRouter } from "next/navigation";

import { MemoryLibrary } from "@/components/MemoryLibrary";

export default function NovelMemoryPage() {
  const params = useParams();
  const router = useRouter();
  const docId = Number(params.id);

  const back = useCallback(() => {
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
      {/* Header */}
      <div
        className="flex items-center gap-sp-3 px-sp-5 py-sp-3 border-b shrink-0"
        style={{ borderColor: "var(--border-subtle)", background: "var(--surface)" }}
      >
        <button
          type="button"
          onClick={back}
          className="w-7 h-7 flex items-center justify-center rounded-sm transition-colors shrink-0"
          style={{ color: "var(--muted)" }}
          title="返回"
          aria-label="返回"
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
          🧠 记忆库
        </h1>
        <span className="text-[11px] truncate" style={{ color: "var(--muted)" }}>
          AI 检索的全部依据——在此整理，改动后台自动重新索引
        </span>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto min-h-0 px-sp-6 py-sp-4">
        <div className="mx-auto" style={{ maxWidth: 980 }}>
          <MemoryLibrary docId={docId} />
        </div>
      </div>
    </main>
  );
}
