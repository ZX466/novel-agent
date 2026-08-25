import { act, fireEvent, render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreativeKitDialog } from "@/components/CreativeKitDialog";
import {
  applyCreativeKit,
  EMPTY_KIT,
  type CreativeKitPackage,
} from "@/lib/creative-kit";
import type { EditorDoc } from "@/lib/types";

// Controllable useChat state so tests can drive generation → parse.
const chat = vi.hoisted(() => ({
  status: "ready" as string,
  messages: [] as Array<{ role: string; parts: Array<{ type: string; text: string }> }>,
  sendMessage: vi.fn(),
}));

vi.mock("@ai-sdk/react", () => ({
  useChat: () => ({
    messages: chat.messages,
    sendMessage: chat.sendMessage,
    status: chat.status,
  }),
}));

vi.mock("@/lib/settings", () => ({
  loadProviderConfig: () => null,
  ownerAuthHeaders: () => ({}),
}));

vi.mock("@/lib/config", () => ({ chatEndpoint: "/api/chat" }));

vi.mock("@/lib/creative-kit", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/creative-kit")>();
  return { ...actual, applyCreativeKit: vi.fn() };
});

const KIT: CreativeKitPackage = {
  world_settings: [{ title: "大陆", category: "地理", content_text: "九州" }],
  characters: [{ name: "主角", role: "主角", description: "d", attributes: { 性格: "冷静" }, arc_summary: "成长" }],
  outline: "第一章：开局。",
};
const DOC = { id: 9, metadata_json: { outline: "第一章：开局。" } } as unknown as EditorDoc;

/** Renders a trigger + the dialog and re-renders the whole fragment so the
 *  controllable useChat mock's new value is picked up on demand. */
function dialogTree(
  open: boolean,
  onClose: () => void,
  onApplied?: (d: EditorDoc) => void,
) {
  return (
    <div>
      <button data-testid="trigger">open kit</button>
      <CreativeKitDialog docId={9} open={open} onClose={onClose} onApplied={onApplied} />
    </div>
  );
}

function finishGeneration(
  rerender: (tree: ReactElement) => void,
  onClose: () => void,
  onApplied?: (d: EditorDoc) => void,
) {
  chat.status = "submitted";
  rerender(dialogTree(true, onClose, onApplied));
  chat.status = "ready";
  chat.messages = [{ role: "assistant", parts: [{ type: "text", text: JSON.stringify(KIT) }] }];
  rerender(dialogTree(true, onClose, onApplied));
}

describe("CreativeKitDialog", () => {
  beforeEach(() => {
    chat.status = "ready";
    chat.messages = [];
    vi.mocked(applyCreativeKit).mockReset();
    vi.mocked(applyCreativeKit).mockResolvedValue({
      created_world_settings: 1,
      skipped_world_settings: 0,
      created_characters: 1,
      skipped_characters: 0,
      outline_applied: true,
      document: DOC as never,
    });
  });

  it("renders nothing when closed", () => {
    render(dialogTree(false, vi.fn()));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("moves initial focus into the dialog on open", () => {
    const onClose = vi.fn();
    const onApplied = vi.fn();
    const { rerender } = render(dialogTree(false, onClose, onApplied));
    act(() => screen.getByTestId("trigger").focus());
    act(() => rerender(dialogTree(true, onClose, onApplied)));
    expect(document.activeElement).toBe(screen.getByRole("dialog"));
  });

  it("returns focus to the trigger on close", () => {
    const onClose = vi.fn();
    const onApplied = vi.fn();
    const { rerender } = render(dialogTree(false, onClose, onApplied));
    act(() => screen.getByTestId("trigger").focus());
    act(() => rerender(dialogTree(true, onClose, onApplied)));
    expect(document.activeElement).toBe(screen.getByRole("dialog"));
    act(() => rerender(dialogTree(false, onClose, onApplied)));
    expect(document.activeElement).toBe(screen.getByTestId("trigger"));
  });

  it("closes on Escape", () => {
    const onClose = vi.fn();
    render(dialogTree(true, onClose));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("wraps Tab focus inside the dialog (focus trap)", () => {
    const onClose = vi.fn();
    render(dialogTree(true, onClose));
    const dialog = screen.getByRole("dialog");
    const cells = Array.from(
      dialog.querySelectorAll<HTMLElement>("button, input, select"),
    ).filter((el) => !el.hasAttribute("disabled"));
    expect(cells.length).toBeGreaterThanOrEqual(2);
    const first = cells[0]!;
    const last = cells[cells.length - 1]!;
    act(() => last.focus());
    fireEvent.keyDown(document, { key: "Tab" });
    expect(document.activeElement).toBe(first);
  });

  it("applies a generated kit via the single batch call and syncs the parent", async () => {
    const onClose = vi.fn();
    const onApplied = vi.fn();
    const { rerender } = render(dialogTree(true, onClose, onApplied));
    finishGeneration(rerender, onClose, onApplied);

    expect(await screen.findByText("生成结果（可检查后应用）")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "应用到作品" }));

    expect(applyCreativeKit).toHaveBeenCalledTimes(1);
    const [docId, body] = vi.mocked(applyCreativeKit).mock.calls[0]!;
    expect(docId).toBe(9);
    // Batch body is the structured kit — no whole-document metadata round-trip.
    expect(body.world_settings[0].title).toBe("大陆");
    expect(body.characters[0].name).toBe("主角");
    expect(body.outline).toContain("第一章");

    expect(await screen.findByText(/已应用：世界观 1/)).toBeInTheDocument();
    // Parent is handed the freshest document (no stale metadata overwrite).
    expect(onApplied).toHaveBeenCalledWith(DOC);
  });

  it("shows an empty-kit hint when nothing could be parsed", async () => {
    const onClose = vi.fn();
    const onApplied = vi.fn();
    const { rerender } = render(dialogTree(true, onClose, onApplied));
    chat.status = "submitted";
    rerender(dialogTree(true, onClose, onApplied));
    chat.status = "ready";
    chat.messages = [{ role: "assistant", parts: [{ type: "text", text: JSON.stringify(EMPTY_KIT) }] }];
    rerender(dialogTree(true, onClose, onApplied));
    expect(await screen.findByText(/未能解析出结构化设定/)).toBeInTheDocument();
  });
});