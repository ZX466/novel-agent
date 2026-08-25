"use client";

import type { ExportFormat } from "@/lib/export";
import type { SafetyScanReport } from "@/lib/safety";

interface SafetyScanDialogProps {
  open: boolean;
  report: SafetyScanReport | null;
  loading: boolean;
  error: string | null;
  /** When set, the dialog offers "仍要导出" to continue a pending export. */
  pendingExport: ExportFormat | null;
  onClose: () => void;
  onContinueExport: () => void;
  onRescan: () => void;
}

const CATEGORY_LABELS: Record<string, string> = {
  pii: "隐私信息",
  privacy: "联系方式",
  copyright: "版权 / 引用",
  sensitive: "敏感表达",
  violence: "暴力内容",
  self_harm: "自伤 / 自杀",
  sexual: "涉性内容",
  hate: "仇恨言论",
  profanity: "粗口",
};

const SEVERITY_COLORS: Record<string, string> = {
  INFO: "var(--muted)",
  WARNING: "oklch(0.74 0.15 75)",
  BLOCK: "var(--danger)",
};

function categoryLabel(category: string): string {
  return CATEGORY_LABELS[category] ?? category;
}

export function SafetyScanDialog({
  open,
  report,
  loading,
  error,
  pendingExport,
  onClose,
  onContinueExport,
  onRescan,
}: SafetyScanDialogProps) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div
        className="fixed inset-0"
        style={{ background: "rgba(0,0,0,0.45)" }}
        onClick={onClose}
      />
      <div
        className="relative z-10 w-full max-w-[480px] max-h-[70vh] flex flex-col rounded-md border shadow-xl"
        style={{ background: "var(--surface)", borderColor: "var(--border-hairline)" }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-sp-4 py-sp-3 border-b shrink-0"
          style={{ borderColor: "var(--border-subtle)" }}
        >
          <div className="flex items-center gap-sp-2">
            <span className="text-[14px]">🛰️</span>
            <h2 className="text-[14px] font-semibold" style={{ color: "var(--fg)" }}>
              交稿雷达
            </h2>
            {report && (
              <span
                className="text-[10px] px-sp-1.5 py-[2px] rounded-sm"
                style={{ background: "var(--surface-2)", color: "var(--muted)" }}
              >
                {report.cached ? "已缓存" : "本次扫描"}
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭"
            className="w-6 h-6 flex items-center justify-center rounded-sm transition-colors"
            style={{ color: "var(--muted)" }}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 min-h-0 overflow-y-auto px-sp-4 py-sp-3 flex flex-col gap-sp-2">
          {loading && (
            <p className="text-[12px] flex items-center gap-sp-2" style={{ color: "var(--muted)" }}>
              <span
                className="w-[5px] h-[5px] rounded-full"
                style={{ background: "var(--accent)", animation: "pulse 1.2s infinite" }}
              />
              扫描中…
            </p>
          )}
          {!loading && error && (
            <div className="text-[12px] py-sp-2" style={{ color: "var(--danger)" }}>
              {error}
            </div>
          )}
          {!loading && !error && report && report.findings.length === 0 && (
            <div className="flex items-center gap-sp-2 text-[13px]" style={{ color: "var(--success)" }}>
              <span>✓</span>
              <span>
                未发现明显隐私 / 版权 / 敏感表达问题（检查 {report.rules_checked} 条规则）。
              </span>
            </div>
          )}
          {!loading && !error && report && report.findings.length > 0 && (
            <div className="flex flex-col gap-sp-2">
              {report.truncated && (
                <p className="text-[11px]" style={{ color: "var(--muted)" }}>
                  文档过长，仅扫描了前 500,000 字符。
                </p>
              )}
              <ul className="flex flex-col gap-sp-2">
                {report.findings.map((f) => (
                  <li
                    key={f.rule_name}
                    className="rounded-sm border px-sp-3 py-sp-2"
                    style={{ borderColor: "var(--border-hairline)" }}
                  >
                    <div className="flex items-center gap-sp-2 text-[12px] font-medium" style={{ color: "var(--fg)" }}>
                      <span className="w-2 h-2 rounded-full shrink-0" style={{ background: SEVERITY_COLORS[f.severity] ?? "var(--muted)" }} />
                      <span>{categoryLabel(f.category)}</span>
                      <span className="font-mono text-[10px]" style={{ color: "var(--fg-tertiary)" }}>
                        {f.rule_name}
                      </span>
                      {f.count > 1 && (
                        <span className="text-[10px]" style={{ color: "var(--muted)" }}>
                          ×{f.count}
                        </span>
                      )}
                    </div>
                    {f.description && (
                      <p className="text-[11px]" style={{ color: "var(--fg-secondary)", marginTop: 6 }}>
                        {f.description}
                      </p>
                    )}
                    {f.sample && (
                      <p className="font-mono text-[11px] break-all" style={{ color: "var(--muted)", marginTop: 6 }}>
                        …{f.sample}…
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {/* Footer */}
        <div
          className="flex items-center justify-end gap-sp-2 px-sp-4 py-sp-3 border-t shrink-0"
          style={{ borderColor: "var(--border-subtle)" }}
        >
          <button
            type="button"
            onClick={onRescan}
            disabled={loading}
            className="text-[12px] px-sp-3 py-[6px] rounded-sm transition-colors font-medium disabled:opacity-40"
            style={{ color: "var(--fg-secondary)", background: "var(--surface-2)" }}
          >
            重新检查
          </button>
          {pendingExport && (
            <button
              type="button"
              onClick={onContinueExport}
              className="text-[12px] px-sp-3 py-[6px] rounded-sm font-medium transition-colors"
              style={{ background: "var(--danger)", color: "var(--bg)" }}
            >
              仍要导出
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            className="text-[12px] px-sp-3 py-[6px] rounded-sm font-medium transition-colors"
            style={{ background: "var(--accent)", color: "var(--bg)" }}
          >
            {pendingExport ? "取消" : "知道了"}
          </button>
        </div>
      </div>
    </div>
  );
}