/**
 * Keyboard-shortcut matching for the editor (R7-1 focus mode).
 *
 * `matchesShortcut` compares a KeyboardEvent-like object against a pattern
 * string such as "Ctrl+S", "Ctrl+Shift+F", "Ctrl+\\" or "Ctrl+Enter".
 * Ctrl matches either the Ctrl or Meta key (Cmd on macOS).
 */

export type Modifier = "ctrl" | "shift" | "alt";

const MODIFIERS: Modifier[] = ["ctrl", "shift", "alt"];

export interface ShortcutKeyEvent {
  ctrlKey: boolean;
  metaKey: boolean;
  shiftKey: boolean;
  altKey: boolean;
  key: string;
}

export function matchesShortcut(e: ShortcutKeyEvent, pattern: string): boolean {
  const parts = pattern
    .split("+")
    .map((p) => p.trim().toLowerCase())
    .filter(Boolean);
  if (parts.length === 0) return false;

  const key = parts[parts.length - 1];
  const has = (m: Modifier) => parts.includes(m);

  // Ctrl pattern accepts Ctrl or Meta (macOS Cmd).
  if (has("ctrl") !== (e.ctrlKey || e.metaKey)) return false;
  if (has("shift") !== e.shiftKey) return false;
  if (has("alt") !== e.altKey) return false;

  // The final segment is the key (modifiers removed).
  const expected = key === "\\" ? "\\" : key.toLowerCase();
  return e.key.toLowerCase() === expected;
}
