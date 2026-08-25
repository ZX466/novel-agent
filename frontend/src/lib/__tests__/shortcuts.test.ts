import { describe, expect, it } from "vitest";

import { matchesShortcut, type ShortcutKeyEvent } from "@/lib/shortcuts";

function ev(overrides: Partial<ShortcutKeyEvent> = {}): ShortcutKeyEvent {
  return {
    ctrlKey: false,
    metaKey: false,
    shiftKey: false,
    altKey: false,
    key: "",
    ...overrides,
  };
}

describe("matchesShortcut", () => {
  it("matches Ctrl+S with ctrl held", () => {
    expect(matchesShortcut(ev({ ctrlKey: true, key: "s" }), "Ctrl+S")).toBe(true);
  });

  it("matches Ctrl+S with Meta (Cmd) on macOS", () => {
    expect(matchesShortcut(ev({ metaKey: true, key: "S" }), "Ctrl+S")).toBe(true);
  });

  it("rejects a bare key without the modifier", () => {
    expect(matchesShortcut(ev({ key: "s" }), "Ctrl+S")).toBe(false);
  });

  it("rejects when an extra shift modifier is pressed", () => {
    expect(matchesShortcut(ev({ ctrlKey: true, shiftKey: true, key: "s" }), "Ctrl+S")).toBe(false);
  });

  it("matches Ctrl+Shift+F (focus toggle)", () => {
    expect(matchesShortcut(ev({ ctrlKey: true, shiftKey: true, key: "f" }), "Ctrl+Shift+F")).toBe(true);
  });

  it("matches Ctrl+\\ (backslash) — key is a backslash char", () => {
    expect(matchesShortcut(ev({ ctrlKey: true, key: "\\" }), "Ctrl+\\")).toBe(true);
  });

  it("matches Ctrl+Enter", () => {
    expect(matchesShortcut(ev({ ctrlKey: true, key: "Enter" }), "Ctrl+Enter")).toBe(true);
  });

  it("rejects Ctrl+\\ when Ctrl+Enter expected", () => {
    expect(matchesShortcut(ev({ ctrlKey: true, key: "\\" }), "Ctrl+Enter")).toBe(false);
  });
});
