"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";

import {
  deleteSnapshot,
  listSnapshots,
  restoreSnapshot,
} from "@/lib/snapshots";
import {
  SNAPSHOT_REASON_LABELS,
  type ChapterSnapshot,
} from "@/lib/types";
import { diffLines, type DiffLine } from "@/lib/diff";

/** Format an ISO timestamp as a relative time string. */
function relativeTime(iso: string): string {
  const ts = new Date(iso).getTime();
  const diff = Date.now() - ts;
  if (Number.isNaN(ts)) return "";
  if (diff < 60_000) return "刚刚";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`;
  const d = new Date(ts);
  return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}`;
}

/** Human label for a snapshot trigger, with a safe fallback. */
function reasonLabel(reason: string): string {
  return SNAPSHOT_REASON_LABELS[reason as keyof typeof SNAPSHOT_REASON_LABELS] ?? reason;
}

// Diff view：将当前编辑器文本与所选快照逐行对比，突出显示差异。

function DiffView({ oldText, newText }: { oldText: string; newText: string }) {
  const lines = useMemo(() => diffLines(oldText, newText), [oldText, newText]);

  if (lines.length === 0) {
    return (
      <div className="flex items-center justify-center h-full" style={{ color: "var(--muted)" }}>
        <p className="text-[12px]">两个版本内容相同</p>
      </div>
    );
  }

  const rowStyle = (line: DiffLine): CSSProperties => {
    if (line.type === "remove") {
      return {
        background: "color-mix(in srgb, var(--danger) 12%, transparent)",
        color: "var(--danger)",
      };
    }
    if (line.type === "add") {
      return {
        background: "color-mix(in srgb, var(--success) 12%, transparent)",
        color: "var(--success)",
      };
    }
    return { color: "var(--fg-secondary)" };
  };

  return (
    <div className="font-mono text-[12px] leading-[1.7] overflow-hidden rounded-sm border" style={{ borderColor: "var(--border-hairline)" }}>
      {lines.map((line, idx) => (
        <div
          key={idx}
          className="flex items-start gap-sp-2 px-sp-2"
          style={rowStyle(line)}
        >
          <span className="w-[2.5rem] shrink-0 text-right select-none" style={{ color: "var(--fg-tertiary)" }}>
            {line.type === "add" ? "" : line.oldLine ?? ""}
          </span>
          <span className="w-[2.5rem] shrink-0 text-right select-none" style={{ color: "var(--fg-tertiary)" }}>
            {line.type === "remove" ? "" : line.newLine ?? ""}
          </span>
          <span className="w-[1.1rem] shrink-0 select-none text-center">
            {line.type === "add" ? "+" : line.type === "remove" ? "-" : " "}
          </span>
          <span className="whitespace-pre-wrap break-words min-w-0 flex-1">
            {line.text || "\u00A0"}
          </span>
        </div>
      ))}
    </div>
  );
}

// Dialog 组件：服务端快照列表 + 预览/对比 + 恢复/删除。

interface VersionHistoryDialogProps {
  open: boolean;
  docId: number;
  chapterId: number | null;
  chapterTitle: string;
  /** Current editor text, used to diff against a selected snapshot. */
  currentText: string;
  onClose: () => void;
  onRestore: (text: string) => void;
}

export function VersionHistoryDialog({
  open,
  docId,
  chapterId,
  chapterTitle,
  currentText,
  onClose,
  onRestore,
}: VersionHistoryDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [snapshots, setSnapshots] = useState<ChapterSnapshot[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null);
  const [compare, setCompare] = useState(false);
  const [restoring, setRestoring] = useState(false);

  const load = useCallback(async () => {
    if (!chapterId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await listSnapshots(docId, chapterId);
      setSnapshots(res.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [docId, chapterId]);

  // Load snapshots when the dialog opens or the chapter changes.
  useEffect(() => {
    if (!open) return;
    setSelectedId(null);
    setConfirmDelete(null);
    setCompare(false);
    void load();
  }, [open, load]);

  // Native dialog lifecycle.
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open) {
      if (!dialog.open) dialog.showModal();
    } else {
      if (dialog.open) dialog.close();
    }
  }, [open]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const handleClose = () => {
      if (open) onClose();
    };
    dialog.addEventListener("close", handleClose);
    return () => dialog.removeEventListener("close", handleClose);
  }, [open, onClose]);

  const selected = snapshots.find((s) => s.id === selectedId) ?? null;

  const handleRestore = async () => {
    if (!selected || !chapterId) return;
    setRestoring(true);
    try {
      await restoreSnapshot(docId, chapterId, selected.id);
      onRestore(selected.content_text);
      onClose();
    } catch (e) {
      alert(`恢复失败：${e instanceof Error ? e.message : "恢复失败"}`);
    } finally {
      setRestoring(false);
    }
  };

  const handleDelete = async (snapId: number) => {
    if (!chapterId) return;
    try {
      await deleteSnapshot(docId, chapterId, snapId);
      setSnapshots((prev) => prev.filter((s) => s.id !== snapId));
      if (selectedId === snapId) setSelectedId(null);
    } catch (e) {
      alert(`删除失败：${e instanceof Error ? e.message : "删除失败"}`);
    } finally {
      setConfirmDelete(null);
    }
  };

  return (
    <dialog
      ref={dialogRef}
      aria-modal="true"
      aria-labelledby="version-history-title"
      className="rounded-lg p-0 w-[min(90vw,760px)] max-h-[80vh] overflow-hidden backdrop:bg-black/60"
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border-hairline)",
        boxShadow: "var(--shadow-lg)",
        color: "var(--fg)",
      }}
    >
      <div className="flex flex-col max-h-[80vh]">
        {/* Header */}
        <header
          className="px-sp-6 py-sp-4 border-b flex items-center justify-between shrink-0"
          style={{ borderColor: "var(--border-subtle)" }}
        >
          <div className="flex flex-col gap-0.5">
            <h2
              id="version-history-title"
              className="font-display text-[15px] font-semibold"
              style={{ color: "var(--fg)", letterSpacing: "-0.01em" }}
            >
              版本历史
            </h2>
            {chapterTitle && (
              <span className="text-[11px]" style={{ color: "var(--muted)" }}>
                {chapterTitle} · 服务端快照，每章最近 50 条
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭"
            className="w-[30px] h-[30px] flex items-center justify-center rounded-sm text-xl transition-colors"
            style={{ color: "var(--muted)" }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = "var(--surface-2)";
              e.currentTarget.style.color = "var(--fg)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = "transparent";
              e.currentTarget.style.color = "var(--muted)";
            }}
          >
            ×
          </button>
        </header>

        {/* Body: snapshot list + preview / diff */}
        <div className="flex-1 flex min-h-0 overflow-hidden">
          {/* Snapshot list */}
          <div
            className="w-[230px] border-r overflow-y-auto shrink-0"
            style={{ borderColor: "var(--border-subtle)" }}
          >
            {loading ? (
              <div className="p-sp-6 text-center">
                <p className="text-[12px]" style={{ color: "var(--muted)" }}>
                  加载中…
                </p>
              </div>
            ) : error ? (
              <div className="p-sp-6 text-center">
                <p className="text-[12px]" style={{ color: "var(--danger)" }}>
                  加载失败
                </p>
                <button
                  type="button"
                  onClick={() => void load()}
                  className="mt-sp-2 px-3 py-1 text-[11px] rounded-sm border transition-colors"
                  style={{ borderColor: "var(--border)", color: "var(--fg-secondary)" }}
                >
                  重试
                </button>
              </div>
            ) : snapshots.length === 0 ? (
              <div className="p-sp-6 text-center">
                <p className="text-[12px]" style={{ color: "var(--muted)" }}>
                  暂无快照
                </p>
                <p className="text-[10px] mt-1" style={{ color: "var(--fg-tertiary)" }}>
                  AI 插入 / 替换 / 导出 / 手动保存时会自动创建
                </p>
              </div>
            ) : (
              snapshots.map((snap) => (
                <div key={snap.id} className="relative group">
                  <button
                    type="button"
                    onClick={() => setSelectedId(snap.id)}
                    className="w-full px-sp-3 py-sp-2.5 text-left border-b transition-colors"
                    style={{
                      borderColor: "var(--border-subtle)",
                      background:
                        selectedId === snap.id ? "var(--accent-bg)" : "transparent",
                    }}
                    onMouseEnter={(e) => {
                      if (selectedId !== snap.id) {
                        e.currentTarget.style.background = "var(--surface-2)";
                      }
                    }}
                    onMouseLeave={(e) => {
                      if (selectedId !== snap.id) {
                        e.currentTarget.style.background = "transparent";
                      }
                    }}
                  >
                    <span
                      className="text-[11px] font-medium block"
                      style={{
                        color:
                          selectedId === snap.id ? "var(--accent)" : "var(--fg-secondary)",
                      }}
                    >
                      {relativeTime(snap.created_at)}
                    </span>
                    <span className="text-[10px]" style={{ color: "var(--fg-tertiary)" }}>
                      {reasonLabel(snap.reason)} · {snap.word_count.toLocaleString()} 字
                    </span>
                  </button>
                  {/* Delete button on hover */}
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setConfirmDelete(snap.id);
                    }}
                    className="absolute top-1 right-1 w-5 h-5 flex items-center justify-center rounded-sm opacity-0 group-hover:opacity-100 transition-opacity"
                    style={{ color: "var(--danger)" }}
                    title="删除此快照"
                  >
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                      <line x1="18" y1="6" x2="6" y2="18" />
                      <line x1="6" y1="6" x2="18" y2="18" />
                    </svg>
                  </button>
                </div>
              ))
            )}
          </div>

          {/* Preview / diff area */}
          <div className="flex-1 overflow-y-auto p-sp-5 min-w-0">
            {selected ? (
              <>
                <div className="flex items-center justify-between mb-sp-3">
                  <span className="text-[11px] font-mono" style={{ color: "var(--fg-tertiary)" }}>
                    {new Date(selected.created_at).toLocaleString()} · {reasonLabel(selected.reason)} · {selected.word_count.toLocaleString()} 字
                  </span>
                  <button
                    type="button"
                    onClick={() => setCompare((v) => !v)}
                    className="px-3 py-1 text-[11px] rounded-sm border transition-colors"
                    style={{
                      borderColor: compare ? "var(--accent)" : "var(--border)",
                      color: compare ? "var(--accent)" : "var(--fg-secondary)",
                      background: compare ? "var(--accent-bg)" : "transparent",
                    }}
                  >
                    {compare ? "预览原文" : "对比当前"}
                  </button>
                </div>
                {compare ? (
                  <DiffView oldText={currentText} newText={selected.content_text} />
                ) : (
                  <pre
                    className="text-[13px] leading-[1.7] whitespace-pre-wrap font-editor"
                    style={{ color: "var(--fg-secondary)" }}
                  >
                    {selected.content_text}
                  </pre>
                )}
              </>
            ) : (
              <div className="flex flex-col items-center justify-center h-full gap-sp-2" style={{ color: "var(--muted)" }}>
                <svg className="w-10 h-10" style={{ color: "var(--border)" }} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="10" />
                  <polyline points="12 6 12 12 16 14" />
                </svg>
                <p className="text-[12px]">选择左侧快照以预览或对比</p>
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <footer
          className="px-sp-6 py-sp-3 border-t flex items-center justify-between shrink-0"
          style={{ borderColor: "var(--border-subtle)" }}
        >
          <span className="text-[10px]" style={{ color: "var(--fg-tertiary)" }}>
            AI 插入 / 替换 / 导出时自动创建 · 每章最多保留 50 条
          </span>
          <div className="flex gap-sp-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-[12px] rounded-sm border transition-colors"
              style={{ borderColor: "var(--border-hairline)", color: "var(--fg-secondary)" }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = "var(--surface-2)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = "transparent";
              }}
            >
              关闭
            </button>
            <button
              type="button"
              onClick={() => void handleRestore()}
              disabled={!selected || restoring}
              className="px-4 py-2 text-[12px] rounded-sm font-medium transition-all disabled:opacity-30 disabled:cursor-not-allowed"
              style={{ background: "var(--accent)", color: "var(--bg)" }}
              onMouseEnter={(e) => {
                if (selected && !restoring) {
                  e.currentTarget.style.background = "var(--accent-hover)";
                  e.currentTarget.style.boxShadow = "var(--shadow-glow)";
                }
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = "var(--accent)";
                e.currentTarget.style.boxShadow = "none";
              }}
            >
              {restoring ? "恢复中…" : "恢复此版本"}
            </button>
          </div>
        </footer>
      </div>

      {/* Confirm delete overlay */}
      {confirmDelete !== null && (
        <div
          className="absolute inset-0 flex items-center justify-center z-50"
          style={{ background: "oklch(0 0 0 / 0.5)" }}
          onClick={() => setConfirmDelete(null)}
        >
          <div
            className="rounded-lg p-sp-5 max-w-[300px] text-center"
            style={{ background: "var(--surface)", border: "1px solid var(--border-hairline)" }}
            onClick={(e) => e.stopPropagation()}
          >
            <p className="text-[13px] mb-sp-4" style={{ color: "var(--fg-secondary)" }}>
              确定删除此快照？
            </p>
            <div className="flex gap-sp-2 justify-center">
              <button
                type="button"
                onClick={() => setConfirmDelete(null)}
                className="px-4 py-2 text-[12px] rounded-sm border transition-colors"
                style={{ borderColor: "var(--border)", color: "var(--fg-secondary)" }}
              >
                取消
              </button>
              <button
                type="button"
                onClick={() => void handleDelete(confirmDelete)}
                className="px-4 py-2 text-[12px] rounded-sm font-medium"
                style={{ background: "var(--danger)", color: "white" }}
              >
                删除
              </button>
            </div>
          </div>
        </div>
      )}
    </dialog>
  );
}
