"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { SaveState } from "@/hooks/use-documents";

interface WordCountBarProps {
  chapterWordCount: number;
  totalWordCount: number;
  saveState: SaveState;
  dirty: boolean;
  onSave: () => void;
  /** Called when the auto-save timer fires (every 30 s) with pending changes. */
  onAutoSave: () => void;
}

/** Format milliseconds since last save as a relative time string. */
function formatSinceSave(ms: number): string {
  if (ms < 5_000) return "刚刚保存";
  if (ms < 60_000) return `${Math.floor(ms / 1_000)} 秒前保存`;
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)} 分钟前保存`;
  return `${Math.floor(ms / 3_600_000)} 小时前保存`;
}

export function WordCountBar({
  chapterWordCount,
  totalWordCount,
  saveState,
  dirty,
  onSave,
  onAutoSave,
}: WordCountBarProps) {
  // Track when the last successful save happened.
  const [lastSaveTime, setLastSaveTime] = useState<number>(Date.now());
  const [now, setNow] = useState<number>(Date.now());

  // Update lastSaveTime when saveState transitions to "saved".
  useEffect(() => {
    if (saveState === "saved") {
      setLastSaveTime(Date.now());
      setNow(Date.now());
    }
  }, [saveState]);

  // Tick every 10 s to update the relative time display.
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 10_000);
    return () => clearInterval(id);
  }, []);

  // Auto-save: every 30 s when dirty.
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (dirty) {
      timerRef.current = setInterval(() => {
        if (dirty) onAutoSave();
      }, 30_000);
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [dirty, onAutoSave]);

  // Ctrl+S manual save shortcut.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault();
        if (dirty) onSave();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [dirty, onSave]);

  // Status display logic.
  const statusColor = useMemo(() => {
    switch (saveState) {
      case "saving": return "var(--warn)";
      case "saved": return "var(--success)";
      case "error": return "var(--danger)";
      default: return dirty ? "var(--warn)" : "var(--border)";
    }
  }, [saveState, dirty]);

  const statusLabel = useMemo(() => {
    switch (saveState) {
      case "saving":
        return "保存中…";
      case "error":
        return "保存失败";
      case "saved":
      case "idle":
        if (dirty) return "未保存";
        return formatSinceSave(now - lastSaveTime);
      default:
        return "已保存";
    }
  }, [saveState, dirty, now, lastSaveTime]);

  return (
    <div
      className="px-sp-5 py-sp-1.5 border-b flex items-center gap-sp-4 shrink-0"
      style={{
        background: "var(--surface-inset)",
        borderColor: "var(--border-subtle)",
      }}
    >
      <span
        className="text-[10px] tabular-nums flex items-center gap-sp-1.5"
        style={{ color: "var(--fg-tertiary)", fontFamily: "var(--font-mono)" }}
      >
        本章 <span className="font-semibold" style={{ color: "var(--fg-secondary)" }}>{chapterWordCount.toLocaleString()}</span> 字
      </span>
      <span
        className="text-[10px] tabular-nums flex items-center gap-sp-1.5"
        style={{ color: "var(--fg-tertiary)", fontFamily: "var(--font-mono)" }}
      >
        总字数 <span className="font-semibold" style={{ color: "var(--fg-secondary)" }}>{totalWordCount.toLocaleString()}</span> 字
      </span>
      <span className="flex-1" />

      {/* Save status */}
      <span
        className="text-[10px] tabular-nums flex items-center gap-sp-1.5"
        style={{ color: saveState === "error" ? "var(--danger)" : "var(--fg-tertiary)", fontFamily: "var(--font-mono)" }}
      >
        <span
          className="w-[5px] h-[5px] rounded-full"
          style={{
            background: statusColor,
            animation: saveState === "saving" ? "pulse 1.2s infinite" : "none",
            boxShadow: saveState === "error" ? `0 0 6px ${statusColor}` : "none",
          }}
        />
        {statusLabel}
      </span>

      {/* Retry button on error */}
      {saveState === "error" && (
        <button
          type="button"
          onClick={onSave}
          className="px-sp-2 py-sp-0.5 rounded-sm text-[9px] font-medium transition-colors"
          style={{
            background: "oklch(0.60 0.16 25 / 0.10)",
            color: "var(--danger)",
            border: "1px solid oklch(0.60 0.16 25 / 0.20)",
          }}
          onMouseEnter={(e) => { e.currentTarget.style.background = "oklch(0.60 0.16 25 / 0.18)"; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = "oklch(0.60 0.16 25 / 0.10)"; }}
        >
          重试
        </button>
      )}
    </div>
  );
}
