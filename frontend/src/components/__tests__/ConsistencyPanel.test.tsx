/**
 * ConsistencyPanel 空态守卫 (09-14 fix): with no active chapter and no
 * editor text, 「开始检查」 must NOT fire the POST — the backend 422s on
 * {chapter_id: null} with 「需要 chapter_id 或非空 content_text」, which
 * surfaced as a bare "请求失败 (422)". The panel must disable the button,
 * explain why, and map the 422 to a friendly message when it slips through.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConsistencyPanel } from "@/components/ConsistencyPanel";

vi.mock("@/lib/consistency", () => ({
  runConsistencyCheck: vi.fn(),
  listConsistencyChecks: vi.fn().mockResolvedValue({ items: [], total: 0 }),
}));

import {
  runConsistencyCheck,
  listConsistencyChecks,
} from "@/lib/consistency";

function setup(props: Partial<Parameters<typeof ConsistencyPanel>[0]> = {}) {
  return render(
    <ConsistencyPanel docId={1} chapterId={null} chapterText="" {...props} />,
  );
}

beforeEach(() => {
  vi.mocked(runConsistencyCheck).mockReset();
  vi.mocked(listConsistencyChecks).mockResolvedValue({ items: [], total: 0 });
});

describe("ConsistencyPanel 空态守卫", () => {
  it("disables 开始检查 when there is no chapter and no text", () => {
    setup();
    const btn = screen.getByText("开始检查");
    expect(btn).toBeDisabled();
    expect(screen.getByTitle(/请先选择章节/)).toBeInTheDocument();
  });

  it("fires the check when text is present", async () => {
    vi.mocked(runConsistencyCheck).mockResolvedValue({ items: [], total: 0 });
    setup({ chapterText: "陈默走进档案局。" });
    const btn = screen.getByText("开始检查");
    expect(btn).not.toBeDisabled();
    fireEvent.click(btn);
    await waitFor(() => expect(runConsistencyCheck).toHaveBeenCalled());
  });

  it("maps a 422 rejection to a friendly message", async () => {
    vi.mocked(runConsistencyCheck).mockRejectedValue(
      new Error("请求失败 (422)"),
    );
    setup({ chapterText: "有文本", chapterId: 5 });
    fireEvent.click(screen.getByText("开始检查"));
    const msg = await screen.findByText(
      /没有可检查的内容/,
      {},
      { timeout: 3000 },
    );
    expect(msg).toBeInTheDocument();
  });

  it("still fires with a chapterId even when text is empty", async () => {
    vi.mocked(runConsistencyCheck).mockResolvedValue({ items: [], total: 0 });
    setup({ chapterId: 5 });
    const btn = screen.getByText("开始检查");
    expect(btn).not.toBeDisabled();
    fireEvent.click(btn);
    await waitFor(() =>
      expect(runConsistencyCheck).toHaveBeenCalledWith(1, { chapter_id: 5 }),
    );
  });
});

// keep the list-load mock referenced so tree-shaking doesn't drop it
void listConsistencyChecks;
