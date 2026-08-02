"use client";

import { useEffect, useRef, useState } from "react";

/** A single version snapshot stored in localStorage. */
export interface VersionSnapshot {
  id: string;
  chapterId: number;
  text: string;
  timestamp: number; // ms since epoch
  wordCount: number;
}

const STORAGE_KEY_PREFIX = "project11:versions:";
const MAX_SNAPSHOTS = 50;

/** Compute the localStorage key for a given chapter. */
function storageKey(chapterId: number): string {
  return `${STORAGE_KEY_PREFIX}${chapterId}`;
}

/** Save a snapshot for a chapter. Caps at MAX_SNAPSHOTS (oldest dropped). */
export function saveSnapshot(chapterId: number, text: string, wordCount: number): void {
  try {
    const key = storageKey(chapterId);
    const existing: VersionSnapshot[] = JSON.parse(localStorage.getItem(key) ?? "[]");
    const snap: VersionSnapshot = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      chapterId,
      text,
      timestamp: Date.now(),
      wordCount,
    };
    const next = [snap, ...existing].slice(0, MAX_SNAPSHOTS);
    localStorage.setItem(key, JSON.stringify(next));
  } catch {
    // localStorage full or unavailable — silently ignore.
  }
}

/** Load all snapshots for a chapter (newest-first). */
function loadSnapshots(chapterId: number): VersionSnapshot[] {
  try {
    return JSON.parse(localStorage.getItem(storageKey(chapterId)) ?? "[]");
  } catch {
    return [];
  }
}

/** Delete a single snapshot. */
function deleteSnapshot(chapterId: number, snapshotId: string): void {
  try {
    const key = storageKey(chapterId);
    const existing: VersionSnapshot[] = JSON.parse(localStorage.getItem(key) ?? "[]");
    const next = existing.filter((s) => s.id !== snapshotId);
    localStorage.setItem(key, JSON.stringify(next));
  } catch {
    // ignore
  }
}

/** Clear all snapshots for a chapter. */
export function clearSnapshots(chapterId: number): void {
  try {
    localStorage.removeItem(storageKey(chapterId));
  } catch {
    // ignore
  }
}

/** Format a timestamp as relative time string. */
function relativeTime(ts: number): string {
  const diff = Date.now() - ts;
  if (diff < 60_000) return "刚刚";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`;
  const d = new Date(ts);
  return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}`;
}

// ── Dialog component ────────────────────────────────────────────────────

interface VersionHistoryDialogProps {
  open: boolean;
  chapterId: number | null;
  chapterTitle: string;
  onClose: () => void;
  onRestore: (text: string) => void;
}

export function VersionHistoryDialog({
  open,
  chapterId,
  chapterTitle,
  onClose,
  onRestore,
}: VersionHistoryDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [snapshots, setSnapshots] = useState<VersionSnapshot[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  // Load snapshots when dialog opens.
  useEffect(() => {
    if (!open || !chapterId) return;
    setSnapshots(loadSnapshots(chapterId));
    setSelectedId(null);
    setConfirmDelete(null);
  }, [open, chapterId]);

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
    const handleClose = () => { if (open) onClose(); };
    dialog.addEventListener("close", handleClose);
    return () => dialog.removeEventListener("close", handleClose);
  }, [open, onClose]);

  const selected = snapshots.find((s) => s.id === selectedId) ?? null;

  const handleRestore = () => {
    if (!selected) return;
    onRestore(selected.text);
    onClose();
  };

  const handleDelete = (snapId: string) => {
    if (!chapterId) return;
    deleteSnapshot(chapterId, snapId);
    setSnapshots((prev) => prev.filter((s) => s.id !== snapId));
    if (selectedId === snapId) setSelectedId(null);
    setConfirmDelete(null);
  };

  return (
    <dialog
      ref={dialogRef}
      aria-modal="true"
      aria-labelledby="version-history-title"
      className="rounded-lg p-0 w-[min(90vw,640px)] max-h-[80vh] overflow-hidden backdrop:bg-black/60"
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
                {chapterTitle} · 本地快照，最近 50 条
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

        {/* Body: snapshot list + preview */}
        <div className="flex-1 flex min-h-0 overflow-hidden">
          {/* Snapshot list */}
          <div
            className="w-[220px] border-r overflow-y-auto shrink-0"
            style={{ borderColor: "var(--border-subtle)" }}
          >
            {snapshots.length === 0 ? (
              <div className="p-sp-6 text-center">
                <p className="text-[12px]" style={{ color: "var(--muted)" }}>
                  暂无历史版本
                </p>
                <p className="text-[10px] mt-1" style={{ color: "var(--fg-tertiary)" }}>
                  保存时自动创建快照
                </p>
              </div>
            ) : (
              snapshots.map((snap) => (
                <div
                  key={snap.id}
                  className="relative group"
                >
                  <button
                    type="button"
                    onClick={() => setSelectedId(snap.id)}
                    className="w-full px-sp-3 py-sp-2.5 text-left border-b transition-colors"
                    style={{
                      borderColor: "var(--border-subtle)",
                      background: selectedId === snap.id ? "var(--accent-bg)" : "transparent",
                    }}
                    onMouseEnter={(e) => {
                      if (selectedId !== snap.id) e.currentTarget.style.background = "var(--surface-2)";
                    }}
                    onMouseLeave={(e) => {
                      if (selectedId !== snap.id) e.currentTarget.style.background = "transparent";
                    }}
                  >
                    <span
                      className="text-[11px] font-medium block"
                      style={{ color: selectedId === snap.id ? "var(--accent)" : "var(--fg-secondary)" }}
                    >
                      {relativeTime(snap.timestamp)}
                    </span>
                    <span className="text-[10px]" style={{ color: "var(--fg-tertiary)" }}>
                      {snap.wordCount.toLocaleString()} 字
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

          {/* Preview area */}
          <div className="flex-1 overflow-y-auto p-sp-5 min-w-0">
            {selected ? (
              <>
                <div className="flex items-center justify-between mb-sp-3">
                  <span className="text-[11px] font-mono" style={{ color: "var(--fg-tertiary)" }}>
                    {new Date(selected.timestamp).toLocaleString()} · {selected.wordCount.toLocaleString()} 字
                  </span>
                </div>
                <pre
                  className="text-[13px] leading-[1.7] whitespace-pre-wrap font-editor"
                  style={{ color: "var(--fg-secondary)" }}
                >
                  {selected.text}
                </pre>
              </>
            ) : (
              <div className="flex flex-col items-center justify-center h-full gap-sp-2" style={{ color: "var(--muted)" }}>
                <svg className="w-10 h-10" style={{ color: "var(--border)" }} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="10" />
                  <polyline points="12 6 12 12 16 14" />
                </svg>
                <p className="text-[12px]">选择左侧快照查看内容</p>
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
            保存时自动创建 · 本地存储
          </span>
          <div className="flex gap-sp-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-[12px] rounded-sm border transition-colors"
              style={{ borderColor: "var(--border-hairline)", color: "var(--fg-secondary)" }}
              onMouseEnter={(e) => { e.currentTarget.style.background = "var(--surface-2)"; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
            >
              关闭
            </button>
            <button
              type="button"
              onClick={handleRestore}
              disabled={!selected}
              className="px-4 py-2 text-[12px] rounded-sm font-medium transition-all disabled:opacity-30 disabled:cursor-not-allowed"
              style={{ background: "var(--accent)", color: "var(--bg)" }}
              onMouseEnter={(e) => {
                if (selected) {
                  e.currentTarget.style.background = "var(--accent-hover)";
                  e.currentTarget.style.boxShadow = "var(--shadow-glow)";
                }
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = "var(--accent)";
                e.currentTarget.style.boxShadow = "none";
              }}
            >
              恢复此版本
            </button>
          </div>
        </footer>
      </div>

      {/* Confirm delete overlay */}
      {confirmDelete && (
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
                onClick={() => handleDelete(confirmDelete)}
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
