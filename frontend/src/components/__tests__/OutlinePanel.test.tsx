/**
 * OutlinePanel 全局模式：「⤢ 全局」弹出居中弹层（样式对齐 CreativeKitDialog），
 * 超长篇大纲获得完整编辑空间；点遮罩或 ✕ 退出，恢复面板原布局。
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

  it("全局模式 opens a centered modal dialog", () => {
    setup();
    // Enter edit mode first so the textarea is visible.
    fireEvent.click(screen.getByText("编辑"));
    fireEvent.click(screen.getByTitle(/全局模式/));
    const dialog = screen.getByRole("dialog");
    expect(dialog.className).toContain("fixed");
    expect(dialog.className).toContain("z-50");
    const textarea = screen.getByPlaceholderText(/在此编写或粘贴小说大纲/);
    expect(textarea).toHaveClass("flex-1");
    // Close via the ✕ button.
    fireEvent.click(screen.getByLabelText("退出全局模式"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("closes the modal when the overlay is clicked", () => {
    setup();
    fireEvent.click(screen.getByText("编辑"));
    fireEvent.click(screen.getByTitle(/全局模式/));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("全局模式遮罩"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
