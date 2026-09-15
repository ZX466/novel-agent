/**
 * 09-15 回归:生成正文"内容重复"——generate 全链上 draft_node(初稿)和
 * refine_node(润色稿)用同一个 on_token 回调把两段文本流进同一个 SSE
 * 文本流,前端把它们拼成一个 text part → 面板显示"初稿+润色稿"拼接体,
 * 用户插入后章节内容重复(实测第9章:同一段故事写了两遍,4286字)。
 *
 * 修复:transport 侧,收到「refine 阶段开始」的 stage 事件时,结束当前
 * text part 并开启新 text part(text-1)。AI SDK 对 text-end + 新
 * text-start 的语义是"新 part 替换旧 part 展示"——useChat 的 message
 * parts 数组里后一个 text part 排在前一个之后,而面板取最新内容时用
 * parts 里最后一个 text part,因此最终展示/插入的是润色稿。
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PerfChatTransport } from "../perf-transport";
import type { PipelinePerf, StageEvent } from "../perf-transport";

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

describe("多阶段文本分段(refine 开始 → 新 text part)", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("draft 段后收到 refine started → text-end + text-start,后续 delta 归新 part", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      sseResponse([
        'data: {"type":"data-stage","data":{"type":"stage","stage":"draft","status":"started"}}\n\n',
        'data: {"type":"text-delta","delta":"初稿A"}\n\n',
        'data: {"type":"text-delta","delta":"初稿B"}\n\n',
        'data: {"type":"data-stage","data":{"type":"stage","stage":"refine","status":"started"}}\n\n',
        'data: {"type":"text-delta","delta":"润色C"}\n\n',
        'data: {"type":"text-delta","delta":"润色D"}\n\n',
        "data: [DONE]\n\n",
      ]) as unknown as Response,
    );

    const transport = new PerfChatTransport({
      api: "https://test.local/v1/chat",
      onPerf: () => {},
    });
    const stream = await transport.sendMessages({
      trigger: "submit-message",
      chatId: "t",
      messageId: undefined,
      messages: [],
      abortSignal: undefined,
    });
    const reader = stream.getReader();
    const chunks: Array<{ type: string; id?: string; delta?: string }> = [];
    for (;;) {
      const r = await reader.read();
      if (r.done) break;
      chunks.push(r.value as { type: string; id?: string; delta?: string });
    }

    const events = chunks.map((c) => `${c.type}${c.id ? ":" + c.id : ""}${c.delta ? ":" + c.delta : ""}`);
    // 期望序列:draft deltas 用 text-0;refine started 后 text-0 结束、
    // text-1 开始;refine deltas 挂 text-1;流末 text-1 收尾。
    expect(events).toEqual([
      "text-start:text-0",
      "text-delta:text-0:初稿A",
      "text-delta:text-0:初稿B",
      "text-end:text-0",
      "text-start:text-1",
      "text-delta:text-1:润色C",
      "text-delta:text-1:润色D",
      "text-end:text-1",
    ]);
  });

  it("无 refine 阶段(continue 等)保持单 part 行为不变", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      sseResponse([
        'data: {"type":"text-delta","delta":"单段"}\n\n',
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
    expect(chunks.map((c) => `${c.type}:${c.id ?? ""}`)).toEqual([
      "text-start:text-0",
      "text-delta:text-0",
      "text-end:text-0",
    ]);
  });

  it("evaluate 回炉再 refine(第二次 refine started)不重复切段", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      sseResponse([
        'data: {"type":"text-delta","delta":"初稿"}\n\n',
        'data: {"type":"data-stage","data":{"type":"stage","stage":"refine","status":"started","iteration":0}}\n\n',
        'data: {"type":"text-delta","delta":"润色一"}\n\n',
        'data: {"type":"data-stage","data":{"type":"stage","stage":"refine","status":"started","iteration":1}}\n\n',
        'data: {"type":"text-delta","delta":"润色二"}\n\n',
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
    const chunks: Array<{ type: string; id?: string; delta?: string }> = [];
    for (;;) {
      const r = await reader.read();
      if (r.done) break;
      chunks.push(r.value as { type: string; id?: string; delta?: string });
    }
    const starts = chunks.filter((c) => c.type === "text-start");
    expect(starts.map((c) => c.id)).toEqual(["text-0", "text-1"]); // 只切一次
    expect(chunks.filter((c) => c.type === "text-delta" && c.id === "text-1").map((c) => c.delta)).toEqual([
      "润色一",
      "润色二",
    ]);
  });

  it("stage 事件仍转发给 onStage(切段不影响事件 sink)", async () => {
    const stages: StageEvent[] = [];
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      sseResponse([
        'data: {"type":"data-stage","data":{"type":"stage","stage":"refine","status":"started"}}\n\n',
        'data: {"type":"text-delta","delta":"x"}\n\n',
        "data: [DONE]\n\n",
      ]) as unknown as Response,
    );
    const perf: PipelinePerf[] = [];
    const transport = new PerfChatTransport({
      api: "https://t.local",
      onPerf: (p) => perf.push(p),
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
    expect(stages).toHaveLength(1);
    expect(stages[0]).toMatchObject({ stage: "refine", status: "started" });
  });
});
