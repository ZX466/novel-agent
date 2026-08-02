"use client";

import type { Editor as TiptapEditor } from "@tiptap/react";
import { EditorContent } from "@tiptap/react";

import type { SaveState } from "@/hooks/use-documents";

interface EditorProps {
  editor: TiptapEditor | null;
  title: string;
  onTitleChange: (v: string) => void;
  dirty: boolean;
  saveState: SaveState;
  activeLoading: boolean;
  error: string | null;
  onSave: () => void;
  onSaveAsNew: () => void;
  focusMode?: boolean;
  onToggleFocus?: () => void;
}

export function Editor({
  editor,
  title,
  onTitleChange,
  dirty,
  saveState,
  activeLoading,
  error,
  onSave,
  onSaveAsNew,
  focusMode,
  onToggleFocus,
}: EditorProps) {
  if (!editor) {
    return (
      <section
        className="flex items-center justify-center h-full"
        style={{ background: "var(--bg-warm)" }}
      >
        <p className="text-[13px]" style={{ color: "var(--muted)" }}>
          Loading editor…
        </p>
      </section>
    );
  }

  const saveDisabled = !dirty || saveState === "saving" || title.trim().length === 0;
  const saveAsNewDisabled = saveState === "saving" || title.trim().length === 0;

  return (
    <section className="flex flex-col h-full w-full overflow-hidden" style={{ background: "var(--bg)" }}>
      {/* Editor header */}
      <header
        className="px-sp-6 py-sp-3 border-b flex flex-wrap items-center gap-sp-3 shrink-0"
        style={{
          background: "var(--surface)",
          borderColor: "var(--border-subtle)",
        }}
      >
        {/* Title input */}
        <input
          type="text"
          value={title}
          onChange={(e) => onTitleChange(e.target.value)}
          placeholder="文档标题…"
          className="flex-1 min-w-[120px] bg-transparent border-b border-transparent text-[17px] font-medium font-display py-1 outline-none transition-colors"
          style={{
            color: "var(--fg)",
            letterSpacing: "-0.01em",
          }}
          onFocus={(e) => { e.currentTarget.style.borderBottomColor = "var(--accent-muted)"; }}
          onBlur={(e) => { e.currentTarget.style.borderBottomColor = "transparent"; }}
          aria-label="文档标题"
        />

        {/* Toolbar */}
        <div className="flex items-center gap-[2px]">
          <ToolbarButton
            label="B"
            onClick={() => editor.chain().focus().toggleBold().run()}
            active={editor.isActive("bold")}
          />
          <ToolbarButton
            label="I"
            onClick={() => editor.chain().focus().toggleItalic().run()}
            active={editor.isActive("italic")}
          />
          <ToolbarButton
            label="H2"
            onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
            active={editor.isActive("heading", { level: 2 })}
          />
          <ToolbarButton
            label="• List"
            onClick={() => editor.chain().focus().toggleBulletList().run()}
            active={editor.isActive("bulletList")}
          />
        </div>

        <span className="flex-1" />
      </header>

      {/* Loading indicator */}
      {activeLoading && (
        <div
          className="px-sp-6 py-1 text-xs flex items-center gap-sp-2 shrink-0"
          style={{
            color: "var(--accent)",
            background: "var(--accent-bg)",
          }}
        >
          <span
            className="w-[5px] h-[5px] rounded-full"
            style={{
              background: "var(--accent)",
              animation: "pulse 1.2s infinite",
            }}
          />
          加载文档中…
        </div>
      )}

      {/* Error indicator */}
      {error && (
        <div
          className="px-sp-6 py-1 text-xs shrink-0"
          style={{
            color: "var(--danger)",
            background: "oklch(0.60 0.16 25 / 0.08)",
          }}
        >
          {error}
        </div>
      )}

      {/* Editor content area */}
      <div
        className="flex-1 overflow-y-auto px-sp-10 py-sp-8"
        style={{ background: "var(--bg-warm)" }}
      >
        <div
          className="mx-auto font-editor text-[17px] leading-[1.8] max-w-[680px]"
          style={{ color: "var(--fg-secondary)", caretColor: "var(--accent)" }}
        >
          <EditorContent editor={editor} />
        </div>
      </div>

      {/* Editor footer — status bar */}
      <div
        className="px-sp-6 py-sp-2 border-t flex items-center gap-sp-3 shrink-0"
        style={{
          background: "var(--surface)",
          borderColor: "var(--border-subtle)",
        }}
      >
        <span
          className="text-[11px] flex items-center gap-sp-2 font-mono"
          style={{ color: "var(--muted)", letterSpacing: "0.02em" }}
        >
          <span
            className="w-[5px] h-[5px] rounded-full"
            style={{
              background: saveState === "saved"
                ? "var(--success)"
                : saveState === "saving"
                  ? "var(--accent)"
                  : dirty
                    ? "var(--warn)"
                    : "var(--border)",
              animation: saveState === "saving" ? "pulse 1.2s infinite" : "none",
            }}
          />
          {saveState === "saving" ? "保存中…" : saveState === "saved" ? "已保存" : dirty ? "未保存" : "无更改"}
        </span>

        {/* Word count stats */}
        <EditorStats editor={editor} />

        <span className="flex-1" />

        {/* Focus mode toggle */}
        <button
          type="button"
          onClick={onToggleFocus}
          title={focusMode ? "退出专注模式" : "专注模式 (Ctrl+Shift+F)"}
          aria-label={focusMode ? "退出专注模式" : "专注模式"}
          className="w-7 h-7 flex items-center justify-center rounded-sm transition-all"
          style={{
            color: focusMode ? "var(--accent)" : "var(--muted)",
            background: focusMode ? "var(--accent-bg)" : "transparent",
          }}
          onMouseEnter={(e) => {
            if (!focusMode) {
              e.currentTarget.style.background = "var(--surface-2)";
              e.currentTarget.style.color = "var(--fg)";
            }
          }}
          onMouseLeave={(e) => {
            if (!focusMode) {
              e.currentTarget.style.background = "transparent";
              e.currentTarget.style.color = "var(--muted)";
            }
          }}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3" />
          </svg>
        </button>

        <button
          type="button"
          onClick={onSaveAsNew}
          disabled={saveAsNewDisabled}
          className="text-xs font-medium px-4 py-[6px] rounded-sm border transition-all disabled:opacity-30 disabled:cursor-not-allowed"
          style={{
            borderColor: "var(--border-hairline)",
            color: "var(--fg-secondary)",
            letterSpacing: "0.02em",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = "var(--surface-2)";
            e.currentTarget.style.borderColor = "var(--muted)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = "transparent";
            e.currentTarget.style.borderColor = "var(--border-hairline)";
          }}
          title="保存为新文档"
        >
          另存为新文档
        </button>

        <SaveButton dirty={dirty} saveState={saveState} disabled={saveDisabled} onClick={onSave} />
      </div>
    </section>
  );
}

function ToolbarButton({
  label,
  onClick,
  active,
}: {
  label: string;
  onClick: () => void;
  active: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-[30px] h-7 flex items-center justify-center rounded-sm text-xs font-semibold transition-colors"
      style={{
        background: active ? "var(--accent-bg)" : "transparent",
        color: active ? "var(--accent)" : "var(--muted)",
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
      {label}
    </button>
  );
}

function SaveButton({
  dirty,
  saveState,
  disabled,
  onClick,
}: {
  dirty: boolean;
  saveState: SaveState;
  disabled: boolean;
  onClick: () => void;
}) {
  let label = "保存";
  let bg = "var(--accent)";
  let color = "var(--bg)";

  if (saveState === "saving") {
    label = "保存中…";
    bg = "var(--accent-muted)";
  } else if (saveState === "saved") {
    label = "已保存 ✓";
    bg = "var(--success)";
  } else if (saveState === "error") {
    label = "保存失败";
    bg = "var(--danger)";
  } else if (dirty) {
    label = "保存 *";
  }

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="text-xs font-medium px-4 py-[6px] rounded-sm transition-all disabled:opacity-30 disabled:cursor-not-allowed"
      style={{
        background: bg,
        color,
        letterSpacing: "0.02em",
      }}
      onMouseEnter={(e) => {
        if (!disabled) e.currentTarget.style.boxShadow = "var(--shadow-glow)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.boxShadow = "none";
      }}
    >
      {label}
    </button>
  );
}

function EditorStats({ editor }: { editor: TiptapEditor }) {
  const text = editor.getText();
  const cjk = (text.match(/[\u4e00-\u9fff\u3400-\u4dbf]/g) || []).length;
  const latin = (text.match(/[a-zA-Z]+/g) || []).length;
  const words = cjk + latin;
  const chars = text.replace(/\s/g, "").length;
  const readingTime = Math.max(1, Math.ceil(words / 300));

  return (
    <div className="editor-footer__stats">
      <span className="editor-footer__stat">
        <span className="editor-footer__stat-value">{words.toLocaleString()}</span>
        <span className="editor-footer__stat-label">字</span>
      </span>
      <span className="editor-footer__stat-divider" />
      <span className="editor-footer__stat">
        <span className="editor-footer__stat-value">{chars.toLocaleString()}</span>
        <span className="editor-footer__stat-label">字符</span>
      </span>
      <span className="editor-footer__stat-divider" />
      <span className="editor-footer__stat">
        <span className="editor-footer__stat-value">{readingTime}</span>
        <span className="editor-footer__stat-label">分钟阅读</span>
      </span>
    </div>
  );
}
