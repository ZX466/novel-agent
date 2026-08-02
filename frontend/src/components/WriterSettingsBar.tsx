"use client";

import { useState } from "react";

export interface WritingSettings {
  writing_type: string;  // 长篇/短篇
  pov: string;           // 第一人称/第三人称
  genre: string;         // 男频/女频/全频
}

const DEFAULT_SETTINGS: WritingSettings = {
  writing_type: "长篇",
  pov: "第三人称",
  genre: "全频",
};

interface WriterSettingsBarProps {
  settings: WritingSettings;
  onChange: (s: WritingSettings) => void;
}

export { DEFAULT_SETTINGS };

export function WriterSettingsBar({ settings, onChange }: WriterSettingsBarProps) {
  const [open, setOpen] = useState(false);

  const options: Array<{
    key: keyof WritingSettings;
    label: string;
    choices: string[];
  }> = [
    { key: "writing_type", label: "篇幅", choices: ["长篇", "短篇"] },
    { key: "pov", label: "视角", choices: ["第一人称", "第三人称"] },
    { key: "genre", label: "频道", choices: ["男频", "女频", "全频"] },
  ];

  return (
    <div
      className="px-sp-5 py-sp-2 border-b flex items-center gap-sp-4 shrink-0"
      style={{ background: "var(--surface)", borderColor: "var(--border-subtle)" }}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-sp-2 px-sp-2.5 py-sp-1 rounded-sm text-[11px] font-medium border transition-colors"
        style={{
          borderColor: "var(--border)",
          color: "var(--fg-secondary)",
          background: open ? "var(--surface-2)" : "transparent",
        }}
      >
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
        </svg>
        写作设置
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" style={{ transform: open ? "rotate(180deg)" : "rotate(0deg)", transition: "transform 0.2s" }}>
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      {/* Quick display of current settings */}
      <div className="flex items-center gap-sp-2 text-[10px]" style={{ color: "var(--fg-tertiary)" }}>
        <span className="px-sp-1.5 py-[2px] rounded-sm" style={{ background: "var(--surface-2)", color: "var(--muted)" }}>
          {settings.writing_type}
        </span>
        <span className="px-sp-1.5 py-[2px] rounded-sm" style={{ background: "var(--surface-2)", color: "var(--muted)" }}>
          {settings.pov}
        </span>
        <span className="px-sp-1.5 py-[2px] rounded-sm" style={{ background: "var(--surface-2)", color: "var(--muted)" }}>
          {settings.genre}
        </span>
      </div>

      {/* Dropdown (inline expand) */}
      {open && (
        <div
          className="flex items-center gap-sp-5 ml-sp-2 pl-sp-3 border-l"
          style={{ borderColor: "var(--border-subtle)" }}
        >
          {options.map((opt) => (
            <div key={opt.key} className="flex items-center gap-sp-1.5">
              <span className="text-[10px] font-medium" style={{ color: "var(--muted)" }}>
                {opt.label}
              </span>
              {opt.choices.map((choice) => (
                <button
                  key={choice}
                  type="button"
                  onClick={() => onChange({ ...settings, [opt.key]: choice })}
                  className="px-sp-2 py-[2px] rounded-sm text-[10px] font-medium border transition-colors"
                  style={{
                    borderColor:
                      settings[opt.key] === choice
                        ? "var(--accent-muted)"
                        : "var(--border)",
                    background:
                      settings[opt.key] === choice
                        ? "var(--accent-bg)"
                        : "transparent",
                    color:
                      settings[opt.key] === choice
                        ? "var(--accent)"
                        : "var(--fg-tertiary)",
                  }}
                >
                  {choice}
                </button>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
