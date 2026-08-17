"use client";

import { useState } from "react";

export type DisplayFontSize = "sm" | "md" | "lg" | "xl";
export type DisplayLineHeight = "compact" | "normal" | "relaxed";
export type DisplayWidth = "narrow" | "normal" | "wide" | "full";

export interface EditorDisplay {
  fontSize: DisplayFontSize;
  lineHeight: DisplayLineHeight;
  width: DisplayWidth;
}

export const DEFAULT_DISPLAY: EditorDisplay = {
  fontSize: "md",
  lineHeight: "normal",
  width: "normal",
};

const DISPLAY_KEY = "project11:editor-display";

/** Read persisted editor display settings (server-safe: returns default). */
export function loadDisplay(): EditorDisplay {
  if (typeof window === "undefined") return DEFAULT_DISPLAY;
  try {
    const raw = window.localStorage.getItem(DISPLAY_KEY);
    if (!raw) return DEFAULT_DISPLAY;
    return { ...DEFAULT_DISPLAY, ...(JSON.parse(raw) as Partial<EditorDisplay>) };
  } catch {
    return DEFAULT_DISPLAY;
  }
}

export function saveDisplay(d: EditorDisplay): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(DISPLAY_KEY, JSON.stringify(d));
}

/** Font sizes applied to the editor content container (inherited by text). */
export const DISPLAY_FONT_SIZES: Record<DisplayFontSize, string> = {
  sm: "16px",
  md: "17px",
  lg: "18.5px",
  xl: "20px",
};

export const DISPLAY_LINE_HEIGHTS: Record<DisplayLineHeight, string> = {
  compact: "1.65",
  normal: "1.8",
  relaxed: "2.1",
};

export const DISPLAY_WIDTHS: Record<DisplayWidth, string> = {
  narrow: "600px",
  normal: "680px",
  wide: "780px",
  full: "100%",
};

interface EditorDisplaySettingsProps {
  display: EditorDisplay;
  onChange: (d: EditorDisplay) => void;
}

/**
 * Compact "显示设置" popover — font size / line height / editor width.
 * The parent owns persistence; this component only reports changes.
 */
export function EditorDisplaySettings({ display, onChange }: EditorDisplaySettingsProps) {
  const [open, setOpen] = useState(false);

  const sections: Array<{
    label: string;
    key: keyof EditorDisplay;
    choices: Array<{ value: EditorDisplay[keyof EditorDisplay]; label: string }>;
  }> = [
    {
      label: "字号",
      key: "fontSize",
      choices: [
        { value: "sm", label: "小" },
        { value: "md", label: "中" },
        { value: "lg", label: "大" },
        { value: "xl", label: "特大" },
      ],
    },
    {
      label: "行距",
      key: "lineHeight",
      choices: [
        { value: "compact", label: "紧凑" },
        { value: "normal", label: "标准" },
        { value: "relaxed", label: "宽松" },
      ],
    },
    {
      label: "宽度",
      key: "width",
      choices: [
        { value: "narrow", label: "窄" },
        { value: "normal", label: "标准" },
        { value: "wide", label: "宽" },
        { value: "full", label: "全宽" },
      ],
    },
  ];

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        title="显示设置（字号 / 行距 / 宽度）"
        aria-label="显示设置"
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
          <path d="M4 7V4h16v3" />
          <path d="M9 20h6" />
          <path d="M12 4v16" />
        </svg>
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div
            className="absolute right-0 top-9 z-40 py-sp-2 px-sp-3 rounded-md border shadow-lg min-w-[248px] space-y-sp-2"
            style={{ background: "var(--surface)", borderColor: "var(--border-hairline)" }}
          >
            {sections.map((s) => (
              <div key={s.key} className="flex items-center gap-sp-2">
                <span className="w-[34px] shrink-0 text-[10px]" style={{ color: "var(--muted)" }}>
                  {s.label}
                </span>
                <div className="flex gap-0.5 flex-wrap">
                  {s.choices.map((c) => {
                    const active = display[s.key] === c.value;
                    return (
                      <button
                        key={c.value as string}
                        type="button"
                        onClick={() => onChange({ ...display, [s.key]: c.value })}
                        className="px-sp-2 py-[3px] rounded-sm text-[10px] font-medium border transition-colors"
                        style={{
                          borderColor: active ? "var(--accent-muted)" : "var(--border)",
                          background: active ? "var(--accent-bg)" : "transparent",
                          color: active ? "var(--accent)" : "var(--fg-tertiary)",
                        }}
                      >
                        {c.label}
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
            <p
              className="text-[9px] pt-sp-1.5 border-t"
              style={{ color: "var(--fg-tertiary)", borderColor: "var(--border-subtle)" }}
            >
              设置自动保存，适用于所有章节
            </p>
          </div>
        </>
      )}
    </div>
  );
}
