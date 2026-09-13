/**
 * OutlinePanel 全局模式 (R10-⑨ fix): entering outline fullscreen must make
 * the textarea fill the panel height — deployed 09-13 the container got
 * flex-1 but the textarea kept its content height, so nothing appeared to
 * change (the chapter list hiding was the only visible effect).
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { OutlinePanel } from "@/components/OutlinePanel";

import type { ChapterListItem } from "@/lib/types";

const chapters: ChapterListItem[] = [
  { id: 1, novel_id: 9, chapter_index: 0, title: "第一章", content_text: "", summary: "", word_count: 0, status: "draft", metadata_json: {}, created_at: "2026-08-19T00:00:00", updated_at: "2026-08-19T00:00:00" },
];

function setup(overrides: Partial<Parameters<typeof OutlinePanel>[0]> = {}) {
  const props: Parameters<typeof OutlinePanel>[0] = {
    chapters,
    activeChapterId: null,
    loading: false,
    outline: "第一章 张三入宗",
    onSelect: vi.fn(),
    onAdd: vi.fn(),
    onDelete: vi.fn(),
    onRename: vi.fn(),
    onReorder: vi.fn(),
    ...overrides,
  };
  render(<OutlinePanel {...props} />);
}

describe("OutlinePanel 全局模式", () => {
  it("toggles 全局 mode and hides the chapter list", () => {
    setup();
    expect(screen.getByText("第一章")).toBeInTheDocument();
    fireEvent.click(screen.getByTitle(/全局模式/));
    expect(screen.queryByText("第一章")).not.toBeInTheDocument();
  });

  it("entering 全局 mode expands the outline editor to fill the panel", () => {
    setup();
    // Enter edit mode first so the textarea is visible.
    fireEvent.click(screen.getByText("编辑"));
    const textarea = screen.getByPlaceholderText(/在此编写或粘贴小说大纲/);
    expect(textarea).not.toHaveClass("flex-1");

    fireEvent.click(screen.getByTitle(/全局模式/));
    // THE fix: in fullscreen the textarea stretches to the container.
    expect(textarea).toHaveClass("flex-1");
    // ...and the wrapping container is flex column (needed for flex-1).
    const container = textarea.parentElement as HTMLElement;
    expect(container.className).toContain("flex-col");
    expect(container.className).toContain("flex-1");
  });
});
