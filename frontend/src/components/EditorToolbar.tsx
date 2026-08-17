"use client";

import { useState, useEffect, useRef } from "react";

interface EditorToolbarProps {
  /** Toggle mobile preview (narrow-screen CSS mode). */
  mobilePreview: boolean;
  onToggleMobilePreview: () => void;
  /** Current theme name. */
  theme: "dark" | "light" | "eye-care";
  onThemeChange: (theme: "dark" | "light" | "eye-care") => void;
  /** Show/hide the find & replace panel. */
  findOpen: boolean;
  onToggleFind: () => void;
  /** Focus mode (hide sidebars) state + toggle. */
  focusActive: boolean;
  onToggleFocus: () => void;
  /** Version history button. */
  onOpenHistory: () => void;
}

export function EditorToolbar({
  mobilePreview,
  onToggleMobilePreview,
  theme,
  onThemeChange,
  findOpen,
  onToggleFind,
  focusActive,
  onToggleFocus,
  onOpenHistory,
}: EditorToolbarProps) {
  return (
    <div
      className="px-sp-4 py-sp-1.5 border-t flex items-center gap-sp-2 shrink-0"
      style={{
        background: "var(--surface)",
        borderColor: "var(--border-subtle)",
      }}
    >
      {/* Mobile preview toggle */}
      <ToolbarIcon
        icon={
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <rect x="5" y="2" width="14" height="20" rx="2" ry="2" />
            <line x1="12" y1="18" x2="12.01" y2="18" />
          </svg>
        }
        active={mobilePreview}
        onClick={onToggleMobilePreview}
        title={mobilePreview ? "退出手机预览" : "手机预览"}
      />

      {/* Theme selector */}
      <ThemeSwitcher theme={theme} onChange={onThemeChange} />

      {/* Focus mode */}
      <ToolbarIcon
        icon={
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 3h6l-2 2-2 2" />
            <path d="M21 3h-6l2 2 2 2" />
            <path d="M3 21h6l-2-2-2-2" />
            <path d="M21 21h-6l2-2 2-2" />
          </svg>
        }
        active={focusActive}
        onClick={onToggleFocus}
        title="专注模式 (Ctrl+Shift+F)"
      />

      {/* Find & replace */}
      <ToolbarIcon
        icon={
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
        }
        active={findOpen}
        onClick={onToggleFind}
        title="查找替换 (Ctrl+H)"
      />

      {/* Version history */}
      <ToolbarIcon
        icon={
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10" />
            <polyline points="12 6 12 12 16 14" />
          </svg>
        }
        active={false}
        onClick={onOpenHistory}
        title="版本历史"
      />

      <span className="flex-1" />

      {/* Help text */}
      <span className="text-[9px]" style={{ color: "var(--fg-tertiary)", fontFamily: "var(--font-mono)" }}>
        Ctrl+S 保存 · Ctrl+H 查找 · Ctrl+Shift+F 专注
      </span>
    </div>
  );
}

// ── Find & Replace bar ──────────────────────────────────────────────────

interface FindReplaceBarProps {
  /** Trigger find in the Tiptap editor. */
  onFind: (query: string) => void;
  onReplace: (query: string, replacement: string) => void;
  onReplaceAll: (query: string, replacement: string) => void;
  onFindNext: () => void;
  onFindPrev: () => void;
  onClose: () => void;
  /** Match position display: "3 / 12" or null if no matches. */
  matchDisplay: string | null;
}

export function FindReplaceBar({
  onFind,
  onReplace,
  onReplaceAll,
  onFindNext,
  onFindPrev,
  onClose,
  matchDisplay,
}: FindReplaceBarProps) {
  const [query, setQuery] = useState("");
  const [replacement, setReplacement] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Trigger find on every query change.
  useEffect(() => {
    onFind(query);
  }, [query, onFind]);

  // Enter key navigates to next match.
  const handleQueryKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault();
      onFindNext();
    }
    if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    }
  };

  return (
    <div
      className="px-sp-4 py-sp-2 border-t flex items-center gap-sp-3 shrink-0"
      style={{ background: "var(--surface-inset)", borderColor: "var(--border-subtle)" }}
    >
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ color: "var(--muted)" }}>
        <circle cx="11" cy="11" r="8" />
        <line x1="21" y1="21" x2="16.65" y2="16.65" />
      </svg>

      <input
        ref={inputRef}
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={handleQueryKeyDown}
        placeholder="查找…"
        className="flex-1 min-w-[80px] bg-transparent border-b border-transparent text-[12px] outline-none py-1"
        style={{ color: "var(--fg)" }}
        onFocus={(e) => { e.currentTarget.style.borderBottomColor = "var(--accent-muted)"; }}
        onBlur={(e) => { e.currentTarget.style.borderBottomColor = "transparent"; }}
      />

      {/* Match count */}
      <span
        className="text-[10px] font-mono min-w-[40px] text-center"
        style={{ color: matchDisplay ? "var(--fg-tertiary)" : "var(--fg-tertiary)" }}
      >
        {matchDisplay ?? "0 / 0"}
      </span>

      {/* Prev / Next */}
      <button
        type="button"
        onClick={onFindPrev}
        disabled={!query}
        className="w-6 h-6 flex items-center justify-center rounded-sm transition-colors disabled:opacity-25"
        style={{ color: "var(--muted)" }}
        title="上一个 (Shift+Enter)"
      >
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="18 15 12 9 6 15" />
        </svg>
      </button>
      <button
        type="button"
        onClick={onFindNext}
        disabled={!query}
        className="w-6 h-6 flex items-center justify-center rounded-sm transition-colors disabled:opacity-25"
        style={{ color: "var(--muted)" }}
        title="下一个 (Enter)"
      >
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      <input
        type="text"
        value={replacement}
        onChange={(e) => setReplacement(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") { e.preventDefault(); onClose(); }
        }}
        placeholder="替换为…"
        className="flex-1 min-w-[80px] bg-transparent border-b border-transparent text-[12px] outline-none py-1"
        style={{ color: "var(--fg-secondary)" }}
        onFocus={(e) => { e.currentTarget.style.borderBottomColor = "var(--accent-muted)"; }}
        onBlur={(e) => { e.currentTarget.style.borderBottomColor = "transparent"; }}
      />

      <button
        type="button"
        onClick={() => onReplace(query, replacement)}
        disabled={!query}
        className="px-sp-2.5 py-sp-1 rounded-sm text-[10px] font-medium border transition-colors disabled:opacity-30"
        style={{ borderColor: "var(--border)", color: "var(--fg-secondary)" }}
      >
        替换
      </button>
      <button
        type="button"
        onClick={() => onReplaceAll(query, replacement)}
        disabled={!query}
        className="px-sp-2.5 py-sp-1 rounded-sm text-[10px] font-medium border transition-colors disabled:opacity-30"
        style={{ borderColor: "var(--border)", color: "var(--fg-secondary)" }}
      >
        全部替换
      </button>

      <button
        type="button"
        onClick={onClose}
        className="w-6 h-6 flex items-center justify-center rounded-sm transition-colors"
        style={{ color: "var(--muted)" }}
        onMouseEnter={(e) => { e.currentTarget.style.background = "var(--surface-2)"; e.currentTarget.style.color = "var(--fg)"; }}
        onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "var(--muted)"; }}
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <line x1="18" y1="6" x2="6" y2="18" />
          <line x1="6" y1="6" x2="18" y2="18" />
        </svg>
      </button>
    </div>
  );
}

// ── Internal helpers ────────────────────────────────────────────────────

function ToolbarIcon({
  icon,
  active,
  onClick,
  title,
}: {
  icon: React.ReactNode;
  active: boolean;
  onClick: () => void;
  title: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-label={title}
      className="w-7 h-7 flex items-center justify-center rounded-sm transition-all"
      style={{
        color: active ? "var(--accent)" : "var(--muted)",
        background: active ? "var(--accent-bg)" : "transparent",
      }}
      onMouseEnter={(e) => {
        if (!active) {
          e.currentTarget.style.background = "var(--surface-2)";
          e.currentTarget.style.color = "var(--fg)";
        }
      }}
      onMouseLeave={(e) => {
        if (!active) {
          e.currentTarget.style.background = "transparent";
          e.currentTarget.style.color = "var(--muted)";
        }
      }}
    >
      {icon}
    </button>
  );
}

function ThemeSwitcher({
  theme,
  onChange,
}: {
  theme: "dark" | "light" | "eye-care";
  onChange: (t: "dark" | "light" | "eye-care") => void;
}) {
  const [open, setOpen] = useState(false);
  const themes: Array<{ key: "dark" | "light" | "eye-care"; label: string; icon: string }> = [
    { key: "dark", label: "深色", icon: "🌙" },
    { key: "light", label: "浅色", icon: "☀️" },
    { key: "eye-care", label: "护眼", icon: "🌿" },
  ];

  const current = themes.find((t) => t.key === theme) ?? themes[0];

  return (
    <div className="relative">
      <ToolbarIcon
        icon={<span className="text-[12px]">{current.icon}</span>}
        active={open}
        onClick={() => setOpen((v) => !v)}
        title="切换主题"
      />
      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div
            className="absolute bottom-9 left-0 z-40 py-sp-1 rounded-md border shadow-lg min-w-[100px]"
            style={{ background: "var(--surface)", borderColor: "var(--border-hairline)" }}
          >
            {themes.map((t) => (
              <button
                key={t.key}
                type="button"
                onClick={() => {
                  onChange(t.key);
                  setOpen(false);
                }}
                className="w-full px-sp-3 py-sp-1.5 flex items-center gap-sp-2 text-[12px] font-medium transition-colors"
                style={{
                  color: t.key === theme ? "var(--accent)" : "var(--fg-secondary)",
                  background: t.key === theme ? "var(--accent-bg)" : "transparent",
                }}
                onMouseEnter={(e) => {
                  if (t.key !== theme) e.currentTarget.style.background = "var(--surface-2)";
                }}
                onMouseLeave={(e) => {
                  if (t.key !== theme) e.currentTarget.style.background = "transparent";
                }}
              >
                <span>{t.icon}</span>
                {t.label}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
