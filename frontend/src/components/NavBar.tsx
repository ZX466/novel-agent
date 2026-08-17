"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { SettingsDialog } from "@/components/SettingsDialog";

const THEME_STORAGE_KEY = "project11:theme";

function getStoredDark(): boolean {
  const t = window.localStorage.getItem(THEME_STORAGE_KEY);
  // Default (:root) is dark; eye-care is a light-toned theme.
  return t === null || t === "dark";
}

function applyTheme(dark: boolean): void {
  const next = dark ? "dark" : "light";
  window.localStorage.setItem(THEME_STORAGE_KEY, next);
  document.documentElement.dataset.theme = next;
}

const NAV_ITEMS = [
  { href: "/", label: "首页" },
  { href: "/novels", label: "我的作品" },
] as const;

export function NavBar() {
  const pathname = usePathname();
  const [settingsOpen, setSettingsOpen] = useState(false);
  // Deterministic initial value (matches SSR) to avoid hydration mismatch;
  // the real stored theme is read after mount below.
  const [isDark, setIsDark] = useState<boolean>(true);

  useEffect(() => {
    setIsDark(getStoredDark());
  }, []);

  return (
    <nav
      className="h-[var(--header-h)] flex items-center px-sp-6 border-b shrink-0 gap-sp-4 z-10 relative"
      style={{
        background: "var(--surface)",
        borderColor: "var(--border-hairline)",
      }}
    >
      {/* Gold rule under header */}
      <div
        className="absolute bottom-[-1px] left-sp-6 right-sp-6 h-px opacity-40"
        style={{
          background:
            "linear-gradient(90deg, transparent, var(--accent-muted) 20%, var(--accent-muted) 80%, transparent)",
        }}
      />

      <div className="flex items-baseline gap-sp-3">
        <Link href="/" className="flex items-baseline gap-sp-2 no-underline">
          <span
            className="w-7 h-7 flex items-center justify-center border rounded-sm font-display text-sm font-semibold shrink-0 relative"
            style={{
              borderColor: "var(--border-hairline)",
              color: "var(--accent)",
              letterSpacing: "-0.02em",
            }}
          >
            P
            <span
              className="absolute bottom-[-1px] left-[3px] right-[3px] h-px opacity-50"
              style={{ background: "var(--accent-muted)" }}
            />
          </span>
          <span
            className="font-display text-xl font-semibold"
            style={{ color: "var(--fg)", letterSpacing: "-0.02em" }}
          >
            Project11
          </span>
          <span
            className="w-px h-[18px] opacity-60"
            style={{ background: "var(--border-hairline)" }}
          />
          <span
            className="text-[10px] font-medium uppercase hidden md:inline"
            style={{ color: "var(--accent-muted)", letterSpacing: "0.08em" }}
          >
            三阶段 LLM 写作工坊
          </span>
        </Link>
      </div>

      <div className="flex items-center gap-sp-1 ml-sp-6">
        {NAV_ITEMS.map((item) => {
          const isActive =
            item.href === "/"
              ? pathname === "/"
              : pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className="px-sp-3 py-sp-2 rounded-sm text-[13px] font-medium no-underline transition-colors"
              style={{
                color: isActive ? "var(--fg)" : "var(--muted)",
                background: isActive ? "var(--surface-2)" : "transparent",
              }}
              onMouseEnter={(e) => {
                if (!isActive) {
                  e.currentTarget.style.background = "var(--surface-2)";
                  e.currentTarget.style.color = "var(--fg)";
                }
              }}
              onMouseLeave={(e) => {
                if (!isActive) {
                  e.currentTarget.style.background = "transparent";
                  e.currentTarget.style.color = "var(--muted)";
                }
              }}
            >
              {item.label}
            </Link>
          );
        })}
      </div>

      <span className="flex-1" />

      {/* Night / Light background toggle */}
      <button
        type="button"
        onClick={() => {
          const next = !isDark;
          setIsDark(next);
          applyTheme(next);
        }}
        aria-label={isDark ? "切换到浅色" : "切换到深色"}
        title={isDark ? "切换到浅色" : "切换到深色"}
        className="w-8 h-8 flex items-center justify-center rounded-sm transition-colors"
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
        {isDark ? (
          /* Sun icon — click to go light */
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="5" />
            <line x1="12" y1="1" x2="12" y2="3" />
            <line x1="12" y1="21" x2="12" y2="23" />
            <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
            <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
            <line x1="1" y1="12" x2="3" y2="12" />
            <line x1="21" y1="12" x2="23" y2="12" />
            <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
            <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
          </svg>
        ) : (
          /* Moon icon — click to go night */
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
          </svg>
        )}
      </button>

      {/* Settings gear */}
      <button
        type="button"
        onClick={() => setSettingsOpen(true)}
        aria-label="API Provider 设置"
        className="w-8 h-8 flex items-center justify-center rounded-sm transition-colors"
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
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
        </svg>
      </button>

      <SettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </nav>
  );
}
