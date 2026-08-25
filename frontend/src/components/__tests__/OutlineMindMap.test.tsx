import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { OutlineMindMap } from "@/components/OutlineMindMap";

import type { ChapterListItem } from "@/lib/types";

const chapters: ChapterListItem[] = [
  { id: 1, novel_id: 9, chapter_index: 0, title: "第一章", content_text: "", summary: "", word_count: 120, status: "draft", metadata_json: {}, created_at: "2026-08-19T00:00:00", updated_at: "2026-08-19T00:00:00" },
  { id: 2, novel_id: 9, chapter_index: 1, title: "第二章", content_text: "", summary: "", word_count: 300, status: "draft", metadata_json: {}, created_at: "2026-08-19T00:00:00", updated_at: "2026-08-19T00:00:00" },
  { id: 3, novel_id: 9, chapter_index: 2, title: "第三章", content_text: "", summary: "", word_count: 80, status: "draft", metadata_json: {}, created_at: "2026-08-19T00:00:00", updated_at: "2026-08-19T00:00:00" },
];

function setup(overrides: Partial<Parameters<typeof OutlineMindMap>[0]> = {}) {
  const onSelect = vi.fn();
  const onContinue = vi.fn();
  const onReorder = vi.fn();
  const onAdd = vi.fn();
  render(
    <OutlineMindMap
      chapters={chapters}
      activeChapterId={null}
      onSelect={onSelect}
      onContinue={onContinue}
      onReorder={onReorder}
      onAdd={onAdd}
      {...overrides}
    />,
  );
  return { onSelect, onContinue, onReorder, onAdd };
}

describe("OutlineMindMap", () => {
  it("renders every chapter node in order with sequence badges", () => {
    setup();
    expect(screen.getByText("第一章")).toBeInTheDocument();
    expect(screen.getByText("第二章")).toBeInTheDocument();
    expect(screen.getByText("第三章")).toBeInTheDocument();
    expect(screen.getAllByText(/^[123]$/)).toHaveLength(3);
  });

  it("selects a chapter on click", () => {
    const { onSelect } = setup();
    fireEvent.click(screen.getByText("第二章"));
    expect(onSelect).toHaveBeenCalledWith(2);
  });

  it("selects a chapter with keyboard Enter", () => {
    const { onSelect } = setup();
    const node = screen.getByText("第一章").closest('[role="button"]');
    expect(node).not.toBeNull();
    fireEvent.keyDown(node!, { key: "Enter" });
    expect(onSelect).toHaveBeenCalledWith(1);
  });

  it("fires continue callback from the per-node continue button", () => {
    const { onContinue } = setup();
    fireEvent.click(screen.getByLabelText("续写章节 第二章"));
    expect(onContinue).toHaveBeenCalledWith(2);
  });

  it("moves a node up with ArrowUp keyboard (indices recomputed)", () => {
    const { onReorder } = setup();
    // Focus chapter 2 (index 1), press ArrowUp -> swaps with chapter 1.
    const node = screen.getByText("第二章").closest('[role="button"]');
    fireEvent.keyDown(node!, { key: "ArrowUp" });
    expect(onReorder).toHaveBeenCalledWith([
      { id: 2, chapter_index: 0 },
      { id: 1, chapter_index: 1 },
      { id: 3, chapter_index: 2 },
    ]);
  });

  it("moves a node down with ArrowDown keyboard", () => {
    const { onReorder } = setup();
    const node = screen.getByText("第二章").closest('[role="button"]');
    fireEvent.keyDown(node!, { key: "ArrowDown" });
    expect(onReorder).toHaveBeenCalledWith([
      { id: 1, chapter_index: 0 },
      { id: 3, chapter_index: 1 },
      { id: 2, chapter_index: 2 },
    ]);
  });

  it("computes downward drag reorder with corrected insert index ([1,2,3,4]-style case)", () => {
    // [1,2,3] drag 1 onto 3 -> insert before target 3 -> [2,1,3]
    // (the pre-fix bug inserted after the original target index: [2,3,1]).
    const { onReorder } = setup({ chapters: chapters.slice(0, 3) });
    fireEvent.dragStart(screen.getByText("第一章").closest('[role="button"]')!);
    fireEvent.dragEnter(screen.getByText("第三章").closest('[role="button"]')!);
    fireEvent.dragEnd(screen.getByText("第一章").closest('[role="button"]')!);
    expect(onReorder).toHaveBeenCalledWith([
      { id: 2, chapter_index: 0 },
      { id: 1, chapter_index: 1 },
      { id: 3, chapter_index: 2 },
    ]);
  });

  it("renders empty state with an add-chapter action", () => {
    const { onAdd } = setup({ chapters: [] });
    expect(screen.getByText(/暂无章节/)).toBeInTheDocument();
    fireEvent.click(screen.getByText(/添加第一章/));
    expect(onAdd).toHaveBeenCalled();
  });
});
