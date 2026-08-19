/**
 * Line-based text diff for the version-history compare view (R5-4 安心回溯).
 *
 * Pure, dependency-free helper: given the old text and the new text it
 * returns the sequence of line edits (equal / add / remove) with 1-based
 * line numbers so the UI can render a unified-style diff inline.
 */

export type DiffLineType = "equal" | "add" | "remove";

export interface DiffLine {
  type: DiffLineType;
  text: string;
  /** 1-based line number in the old text, or null for added lines. */
  oldLine: number | null;
  /** 1-based line number in the new text, or null for removed lines. */
  newLine: number | null;
}

/** Split text into lines. A trailing newline yields a final empty line. */
function toLines(text: string): string[] {
  if (text === "") return [];
  return text.split("\n");
}

/**
 * Guard against pathological inputs: the LCS DP is O(n*m) memory, so when
 * both texts are huge and dissimilar we fall back to a still-correct but
 * verbose "everything removed, everything added" diff instead of freezing
 * the UI. Typical chapters stay far below this threshold.
 */
const MAX_LCS_CELLS = 2_000_000;

/** Backtrack a full LCS table into an ordered list of line edits. */
function trace(a: string[], b: string[]): DiffLine[] {
  const n = a.length;
  const m = b.length;
  // dp[i][j] = LCS length of a[i..] and b[j..]
  const dp: number[][] = Array.from({ length: n + 1 }, () =>
    new Array<number>(m + 1).fill(0),
  );
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] =
        a[i] === b[j]
          ? dp[i + 1][j + 1] + 1
          : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const result: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      result.push({ type: "equal", text: a[i], oldLine: i + 1, newLine: j + 1 });
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      result.push({ type: "remove", text: a[i], oldLine: i + 1, newLine: null });
      i++;
    } else {
      result.push({ type: "add", text: b[j], oldLine: null, newLine: j + 1 });
      j++;
    }
  }
  while (i < n) {
    result.push({ type: "remove", text: a[i], oldLine: i + 1, newLine: null });
    i++;
  }
  while (j < m) {
    result.push({ type: "add", text: b[j], oldLine: null, newLine: j + 1 });
    j++;
  }
  return result;
}

/** Return the ordered line edits turning `oldText` into `newText`. */
export function diffLines(oldText: string, newText: string): DiffLine[] {
  const a = toLines(oldText);
  const b = toLines(newText);
  if (a.length === 0 && b.length === 0) return [];
  if (a.length * b.length > MAX_LCS_CELLS) {
    return [
      ...a.map((text, i) => ({
        type: "remove" as const,
        text,
        oldLine: i + 1,
        newLine: null,
      })),
      ...b.map((text, i) => ({
        type: "add" as const,
        text,
        oldLine: null,
        newLine: i + 1,
      })),
    ];
  }
  return trace(a, b);
}
