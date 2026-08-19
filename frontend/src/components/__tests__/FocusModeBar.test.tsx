import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FocusModeBar } from "@/components/FocusModeBar";

function setup(overrides: Partial<{ title: string; dirty: boolean }> = {}) {
  const onSave = vi.fn();
  const onExit = vi.fn();
  render(
    <FocusModeBar
      title={overrides.title ?? "我的小说"}
      dirty={overrides.dirty ?? false}
      onSave={onSave}
      onExit={onExit}
    />,
  );
  return { onSave, onExit };
}

describe("FocusModeBar", () => {
  it("renders the work title", () => {
    setup({ title: "修仙录" });
    expect(screen.getByText("修仙录")).toBeInTheDocument();
  });

  it("shows keyboard hints", () => {
    setup();
    expect(screen.getByText(/Ctrl\+S 保存/)).toBeInTheDocument();
  });

  it("fires save when dirty and save clicked", () => {
    const { onSave } = setup({ dirty: true });
    fireEvent.click(screen.getByLabelText("保存"));
    expect(onSave).toHaveBeenCalled();
  });

  it("disables save when not dirty", () => {
    const { onSave } = setup({ dirty: false });
    expect(screen.getByLabelText("保存")).toBeDisabled();
    fireEvent.click(screen.getByLabelText("保存"));
    expect(onSave).not.toHaveBeenCalled();
  });

  it("fires exit when exit button clicked", () => {
    const { onExit } = setup();
    fireEvent.click(screen.getByLabelText("退出专注模式"));
    expect(onExit).toHaveBeenCalled();
  });
});
