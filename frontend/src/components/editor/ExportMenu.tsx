"use client";

/**
 * Export dropdown (F3): per-format export with auto-snapshot of the current
 * chapter (best-effort) and a pre-export safety scan (交稿雷达) — findings
 * surface the radar dialog first; export continues only after confirmation.
 */
import { useState } from "react";

import { createSnapshot } from "@/lib/snapshots";
import { downloadExport, EXPORT_LABELS, type ExportFormat } from "@/lib/export";
import { fetchSafetyScan, type SafetyScanReport } from "@/lib/safety";

interface ExportMenuProps {
  docId: number;
  activeChapterId: number | null;
  activeChapterTitle: string | null;
  currentText: string;
  /** Opens the radar dialog with the given preflight report + pending format. */
  onRadarPreflight: (report: SafetyScanReport, fmt: ExportFormat) => void;
}

export function ExportMenu({
  docId,
  activeChapterId,
  activeChapterTitle,
  currentText,
  onRadarPreflight,
}: ExportMenuProps) {
  const [open, setOpen] = useState(false);
  const [exporting, setExporting] = useState<ExportFormat | null>(null);

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        title="导出作品（Markdown / TXT / EPUB）"
        aria-label="导出作品"
        aria-expanded={open}
        className="w-7 h-7 flex items-center justify-center rounded-sm transition-colors"
        style={{
          color: open ? "var(--accent)" : "var(--muted)",
          background: open ? "var(--accent-bg)" : "transparent",
        }}
        onMouseEnter={(e) => {
          if (!open) {
            e.currentTarget.style.background = "var(--surface-2)";
            e.currentTarget.style.color = "var(--fg)";
          }
        }}
        onMouseLeave={(e) => {
          if (!open) {
            e.currentTarget.style.background = "transparent";
            e.currentTarget.style.color = "var(--muted)";
          }
        }}
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
          <polyline points="7 10 12 15 17 10" />
          <line x1="12" y1="15" x2="12" y2="3" />
        </svg>
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div
            className="absolute right-0 top-9 z-40 py-sp-1 rounded-md border shadow-lg min-w-[140px]"
            style={{ background: "var(--surface)", borderColor: "var(--border-hairline)" }}
          >
            {(Object.keys(EXPORT_LABELS) as ExportFormat[]).map((fmt) => (
              <button
                key={fmt}
                type="button"
                disabled={exporting !== null}
                onClick={async () => {
                  setExporting(fmt);
                  try {
                    // Auto-snapshot before exporting so the
                    // current draft is recoverable.
                    if (activeChapterId != null) {
                      try {
                        await createSnapshot(docId, activeChapterId, currentText, {
                          title: activeChapterTitle ?? "",
                          reason: "export",
                        });
                      } catch {
                        // Best-effort; never block the export.
                      }
                    }
                    // 交稿雷达 (R6-3)：导出前自动预检，提示可忽略，不阻塞导出。
                    const preflight = await fetchSafetyScan(docId).catch(() => null);
                    if (preflight && preflight.findings.length > 0) {
                      onRadarPreflight(preflight, fmt);
                      return;
                    }
                    await downloadExport(docId, fmt);
                  } catch (e) {
                    alert(`❌ 导出失败: ${e instanceof Error ? e.message : "未知错误"}`);
                  } finally {
                    setExporting(null);
                    setOpen(false);
                  }
                }}
                className="w-full px-sp-3 py-sp-1.5 flex items-center justify-between gap-sp-2 text-[12px] font-medium transition-colors disabled:opacity-40"
                style={{ color: "var(--fg-secondary)" }}
                onMouseEnter={(e) => { e.currentTarget.style.background = "var(--surface-2)"; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
              >
                <span>{EXPORT_LABELS[fmt]}</span>
                {exporting === fmt && (
                  <span className="w-[4px] h-[4px] rounded-full" style={{ background: "var(--accent)", animation: "pulse 1.2s infinite" }} />
                )}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
