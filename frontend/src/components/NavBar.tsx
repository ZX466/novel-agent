"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { SettingsDialog } from "@/components/SettingsDialog";

const NAV_ITEMS = [
  { href: "/", label: "首页" },
  { href: "/novels", label: "我的作品" },
] as const;

export function NavBar() {
  const pathname = usePathname();
  const [settingsOpen, setSettingsOpen] = useState(false);

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
