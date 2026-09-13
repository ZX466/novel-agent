import { act, fireEvent, render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreativeKitDialog } from "@/components/CreativeKitDialog";
import {
  applyCreativeKit,
  EMPTY_KIT,
  type CreativeKitPackage,
} from "@/lib/creative-kit";
import { getDocument } from "@/lib/documents";
import { listCharacters } from "@/lib/characters";
import { listWorldSettings } from "@/lib/world-settings";
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

// 作品上下文三件套 mock — 每个用例可覆写返回值/抛错。
vi.mock("@/lib/documents", () => ({
  getDocument: vi.fn(),
}));
vi.mock("@/lib/characters", () => ({
  listCharacters: vi.fn(),
}));
vi.mock("@/lib/world-settings", () => ({
  listWorldSettings: vi.fn(),
}));

vi.mock("@/lib/creative-kit", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/creative-kit")>();
  return { ...actual, applyCreativeKit: vi.fn() };
});

const KIT: CreativeKitPackage = {
  world_settings: [{ title: "大陆", category: "地理", content_text: "九州" }],
  characters: [{ name: "主角", role: "主角", description: "d", attributes: { 性格: "冷静" }, arc_summary: "成长" }],
  relationships: [],
  outline: "第一章：开局。",
};
const DOC = { id: 9, metadata_json: { outline: "第一章：开局。" } } as unknown as EditorDoc;

/** Rich fixture for the 作品现状 block: title/description/outline + cast.
 *  简介/大纲 live in metadata_json (CreationWizard stores them there). */
const CONTEXT_DOC = {
  id: 9,
  title: "星陨大陆",
  metadata_json: {
    description: "灵气复苏后的现代都市修仙故事。",
    outline: "第一章 觉醒：少年偶得上古功法。\n第二章 入门：进入青云宗。",
  },
} as unknown as EditorDoc;
const CONTEXT_CHARS = {
  items: [
    { name: "陈默", role: "主角", description: "", attributes: {}, arc_summary: "", id: 1, novel_id: 9, created_at: "", updated_at: "" },
    { name: "林霜", role: "宿敌", description: "", attributes: {}, arc_summary: "", id: 2, novel_id: 9, created_at: "", updated_at: "" },
  ],
  total: 2,
};
const CONTEXT_WORLD = {
  items: [{ title: "灵气复苏纪元", category: "历史", content_text: "", metadata_json: {}, id: 1, novel_id: 9, created_at: "", updated_at: "" }],
  total: 1,
};

/** Default lib-layer mocks: rich context. Individual tests override. */
function mockFullContext() {
  vi.mocked(getDocument).mockResolvedValue(CONTEXT_DOC);
  vi.mocked(listCharacters).mockResolvedValue(CONTEXT_CHARS);
  vi.mocked(listWorldSettings).mockResolvedValue(CONTEXT_WORLD);
}

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
    chat.sendMessage.mockReset();
    vi.mocked(applyCreativeKit).mockReset();
    vi.mocked(applyCreativeKit).mockResolvedValue({
      created_world_settings: 1,
      skipped_world_settings: 0,
      created_characters: 1,
      created_relationships: 0,
      skipped_relationships: 0,
      skipped_characters: 0,
      outline_applied: true,
      document: DOC as never,
    });
    mockFullContext();
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

  describe("作品现状 context injection", () => {
    /** Clicks 一键生成设定包 and flushes the async context fetches so
     *  sendMessage has been called with the fully-built prompt. */
    async function generate() {
      const { rerender } = render(dialogTree(true, vi.fn()));
      fireEvent.click(screen.getByRole("button", { name: "一键生成设定包" }));
      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
        await Promise.resolve();
      });
      return rerender;
    }

    /** Extracts the prompt text captured from sendMessage({ text }). */
    function sentText() {
      expect(chat.sendMessage).toHaveBeenCalledTimes(1);
      const arg = chat.sendMessage.mock.calls[0]![0] as { text: string };
      return arg.text;
    }

    it("fetches document/characters/world-settings before generating", async () => {
      await generate();
      expect(getDocument).toHaveBeenCalledWith(9);
      expect(listCharacters).toHaveBeenCalledWith(9, 500);
      expect(listWorldSettings).toHaveBeenCalledWith(9, { limit: 100 });
    });

    it("injects a 作品现状 block with 标题/简介/角色定位摘要/世界观标题/大纲", async () => {
      await generate();
      const text = sentText();
      expect(text).toContain("作品现状");
      expect(text).toContain("标题：星陨大陆");
      expect(text).toContain("简介：灵气复苏后的现代都市修仙故事。");
      expect(text).toContain("陈默（主角）");
      expect(text).toContain("林霜（宿敌）");
      expect(text).toContain("灵气复苏纪元");
      expect(text).toContain("现有大纲");
      expect(text).toContain("第一章 觉醒：少年偶得上古功法。");
    });

    it("rewrites the instruction line to anchor on the current work", async () => {
      await generate();
      const text = sentText();
      expect(text).toContain(
        "基于作品现状生成与当前故事一致、延续既有设定的灵感套件，世界观与人物不得与已有设定冲突，大纲作为主线参考可扩写但不得推翻既有走向",
      );
    });

    it("keeps the duplicate-name avoidance directive with existing names", async () => {
      await generate();
      const text = sentText();
      expect(text).toContain("严禁再生成同名或明显同人的角色");
      expect(text).toContain("陈默、林霜");
    });

    it("truncates a long outline to 3000 chars", async () => {
      const longOutline = "大".repeat(4000);
      vi.mocked(getDocument).mockResolvedValue({
        ...CONTEXT_DOC,
        metadata_json: { outline: longOutline },
      } as unknown as EditorDoc);
      await generate();
      const text = sentText();
      expect(text).toContain(longOutline.slice(0, 3000));
      expect(text).not.toContain("大".repeat(3001));
    });

    it("still generates when every context fetch fails (empty context)", async () => {
      vi.mocked(getDocument).mockRejectedValue(new Error("network down"));
      vi.mocked(listCharacters).mockRejectedValue(new Error("network down"));
      vi.mocked(listWorldSettings).mockRejectedValue(new Error("network down"));
      await generate();
      const text = sentText();
      expect(text).not.toContain("作品现状");
      expect(text).not.toContain("严禁再生成同名");
      expect(text).toContain("[task:generate]");
    });

    it("still generates when only the document fetch fails", async () => {
      vi.mocked(getDocument).mockRejectedValue(new Error("404"));
      await generate();
      const text = sentText();
      // Cast/world sections still render (from their own fetches).
      expect(text).toContain("陈默（主角）");
      expect(text).not.toContain("标题：星陨大陆");
    });
  });
});