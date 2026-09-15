/**
 * 09-15 P1 回归:"Cannot set properties of undefined (setting 'state')"。
 *
 * 用户报告:生成正文(generate)运行时报这个错。根因在 PerfChatTransport:
 * 后端每条流在 [DONE] 之前都会发一次收尾 `{"type":"text-end","id":"text-0"}`
 * (backend/app/api/chat.py _encode_text_end),transport 的 text-end 分支
 * 转发后没有把 textStarted 置回 false,于是 [DONE] 分支的
 * `if (textStarted) enqueue(text-end)` 兜底又发了一次同 id 的 text-end。
 * AI SDK(processUIMessageStream)的 text-end 处理是
 * `activeTextParts[id].state = "done"` 后 `delete activeTextParts[id]`——
 * 第二个同 id text-end 命中 undefined → 抛 "Cannot set properties of
 * undefined (setting 'state')"。
 *
 * b4f8382 之前不炸:[DONE] 分支不发 text-end,后端的 text-end 全程只有
 * 一次。b4f8382 给 [DONE] 加了收尾兜底,与后端真实收尾撞车——而 4 个
 * stage-split 用例的 mock SSE 序列都没带后端真实的收尾 text-end,漏网。
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

import { PerfChatTransport } from "../perf-transport";
import type { StageEvent } from "../perf-transport";

function sseResponse(frames: string[]): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const f of frames) controller.enqueue(encoder.encode(f));
      controller.close();
    },
  });
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

/** 后端 chat.py 的真实 generate wire 序列:draft 段 → refine 段 →
 *  收尾 text-end → finish → [DONE](text-start/text-delta 由后端发出
 *  时 id 固定 text-0,transport 用自己的 partId 覆盖 id)。 */
const REAL_GENERATE_FRAMES = [
  'data: {"type":"data-pipeline_start","data":{"type":"pipeline_start"}}\n\n',
  'data: {"type":"data-stage","data":{"type":"stage","stage":"retrieval","status":"started"}}\n\n',
  'data: {"type":"data-stage","data":{"type":"stage","stage":"retrieval","status":"succeeded","elapsed_ms":120}}\n\n',
  'data: {"type":"data-stage","data":{"type":"stage","stage":"draft","status":"started"}}\n\n',
  'data: {"type":"text-delta","id":"text-0","delta":"初稿A"}\n\n',
  'data: {"type":"text-delta","id":"text-0","delta":"初稿B"}\n\n',
  'data: {"type":"data-stage","data":{"type":"stage","stage":"draft","status":"succeeded","elapsed_ms":900}}\n\n',
  'data: {"type":"data-stage","data":{"type":"stage","stage":"refine","status":"started"}}\n\n',
  'data: {"type":"text-delta","id":"text-0","delta":"润色C"}\n\n',
  'data: {"type":"text-delta","id":"text-0","delta":"润色D"}\n\n',
  'data: {"type":"data-stage","data":{"type":"stage","stage":"refine","status":"succeeded","elapsed_ms":700}}\n\n',
  'data: {"type":"data-stage","data":{"type":"stage","stage":"evaluate","status":"succeeded","elapsed_ms":50}}\n\n',
  'data: {"type":"data-stage","data":{"type":"stage","stage":"safety_check","status":"succeeded","elapsed_ms":10}}\n\n',
  'data: {"type":"text-end","id":"text-0"}\n\n',
  'data: {"type":"finish","finishReason":"stop"}\n\n',
  "data: [DONE]\n\n",
];

describe("后端真实收尾 text-end 不产生重复 text-end", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("generate 全链:[DONE] 兜底不得与后端收尾 text-end 重复(同 id 只 end 一次)", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      sseResponse(REAL_GENERATE_FRAMES) as unknown as Response,
    );
    const transport = new PerfChatTransport({ api: "https://t.local", onPerf: () => {} });
    const stream = await transport.sendMessages({
      trigger: "submit-message",
      chatId: "t",
      messageId: undefined,
      messages: [],
      abortSignal: undefined,
    });
    const reader = stream.getReader();
    const chunks: Array<{ type: string; id?: string }> = [];
    for (;;) {
      const r = await reader.read();
      if (r.done) break;
      chunks.push(r.value as { type: string; id?: string });
    }

    const ends = chunks.filter((c) => c.type === "text-end");
    // 每个 part id 恰好 end 一次;AI SDK 对重复 end 会抛
    // "Cannot set properties of undefined (setting 'state')"。
    const ids = ends.map((c) => c.id);
    expect(new Set(ids).size).toBe(ids.length);
    // 初稿 part text-0 在切段时 end;润色 part text-1 在后端收尾 end;
    // [DONE] 时不再补发。
    expect(ids).toEqual(["text-0", "text-1"]);
  });

  it("单阶段(continue):后端收尾 text-end + [DONE] 也只 end 一次", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      sseResponse([
        'data: {"type":"text-delta","id":"text-0","delta":"续写内容"}\n\n',
        'data: {"type":"text-end","id":"text-0"}\n\n',
        'data: {"type":"finish","finishReason":"stop"}\n\n',
        "data: [DONE]\n\n",
      ]) as unknown as Response,
    );
    const transport = new PerfChatTransport({ api: "https://t.local", onPerf: () => {} });
    const stream = await transport.sendMessages({
      trigger: "submit-message",
      chatId: "t",
      messageId: undefined,
      messages: [],
      abortSignal: undefined,
    });
    const reader = stream.getReader();
    const chunks: Array<{ type: string; id?: string }> = [];
    for (;;) {
      const r = await reader.read();
      if (r.done) break;
      chunks.push(r.value as { type: string; id?: string });
    }
    expect(chunks.filter((c) => c.type === "text-end").map((c) => c.id)).toEqual(["text-0"]);
  });

  it("阶段事件照常到达 sink(收尾修复不影响 onStage)", async () => {
    const stages: StageEvent[] = [];
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      sseResponse(REAL_GENERATE_FRAMES) as unknown as Response,
    );
    const transport = new PerfChatTransport({
      api: "https://t.local",
      onPerf: () => {},
      onStage: (e) => stages.push(e),
    });
    const stream = await transport.sendMessages({
      trigger: "submit-message",
      chatId: "t",
      messageId: undefined,
      messages: [],
      abortSignal: undefined,
    });
    const reader = stream.getReader();
    for (;;) {
      const r = await reader.read();
      if (r.done) break;
    }
    expect(stages.length).toBeGreaterThanOrEqual(5);
    expect(stages.some((e) => e.stage === "refine" && e.status === "started")).toBe(true);
    // 该序列未包含 perf 帧——perf 有独立用例覆盖(perf-transport.test.ts)。
  });
});
