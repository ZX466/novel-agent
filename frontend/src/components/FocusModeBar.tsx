"use client";

interface FocusModeBarProps {
  title: string;
  dirty: boolean;
  onSave: () => void;
  onExit: () => void;
}

/**
 * Slim top bar shown while in focus mode (R7-1): the work title, a save
 * action, keyboard-hint chips and the exit button. Replaces the full
 * writer-settings / word-count bars so nothing distracts from writing.
 */
export function FocusModeBar({ title, dirty, onSave, onExit }: FocusModeBarProps) {
  return (
    <div
      className="flex items-center gap-sp-3 px-sp-4 shrink-0 border-b"
      style={{
        height: 38,
        background: "var(--surface)",
        borderColor: "var(--border-subtle)",
      }}
    >
      <span
        className="text-[11px] font-medium truncate flex-1 min-w-0"
        style={{ color: "var(--fg-secondary)" }}
        title={title}
      >
        {title}
      </span>

      <span
        className="hidden md:inline text-[10px] tabular-nums"
        style={{ color: "var(--fg-tertiary)", fontFamily: "var(--font-mono)" }}
      >
        Ctrl+S 保存 · Ctrl+Enter 续写 · Ctrl+\ 退出
      </span>

      <button
        type="button"
        onClick={onSave}
        disabled={!dirty}
        className="px-sp-3 py-[3px] rounded-sm text-[11px] font-medium border transition-colors disabled:opacity-40"
        style={{
          borderColor: dirty ? "var(--accent)" : "var(--border)",
          color: dirty ? "var(--accent)" : "var(--muted)",
        }}
        aria-label="保存"
      >
        {dirty ? "保存" : "已保存"}
      </button>

      <button
        type="button"
        onClick={onExit}
        className="px-sp-3 py-[3px] rounded-sm text-[11px] font-medium transition-colors"
        style={{
          color: "var(--muted)",
          border: "1px solid var(--border-hairline)",
        }}
        aria-label="退出专注模式"
        title="Ctrl+\ 退出专注"
      >
        退出专注
      </button>
    </div>
  );
}
