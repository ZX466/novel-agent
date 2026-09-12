import { describe, expect, it, vi, beforeEach } from "vitest";
import { PerfChatTransport } from "../perf-transport";
import type { StageEvent, PipelinePerf } from "../perf-transport";

/**
 * Wire-level regression for the R9-② lesson ("事件到达 ≠ 事件被正确消费"):
 * the backend emits `data:`-prefixed SSE lines with data- wrapped custom
 * events; PerfChatTransport must unwrap and forward them to the sinks, and
 * translate text events into AI SDK UIMessageChunks.
 */

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

describe("PerfChatTransport wire parsing", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("unwraps data-stage / data-pipeline_start and forwards to onStage", async () => {
    const stages: StageEvent[] = [];
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      sseResponse([
        // Fixed backend (type preserved inside data):
        'data: {"type":"data-pipeline_start","data":{"seq":1,"type":"pipeline_start","task_type":"generate"}}\n\n',
        'data: {"type":"data-stage","data":{"seq":2,"type":"stage","stage":"retrieval","status":"started","iteration":0}}\n\n',
        'data: {"type":"data-stage","data":{"seq":3,"type":"stage","stage":"retrieval","status":"succeeded","elapsed_ms":12}}\n\n',
        "data: [DONE]\n\n",
      ]) as unknown as Response,
    );

    const transport = new PerfChatTransport({
      api: "https://test.local/v1/chat",
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
    // Drain the stream to completion (chunks are standard UI chunks).
    const chunks: unknown[] = [];
    for (;;) {
      const r = await reader.read();
      if (r.done) break;
      chunks.push(r.value);
    }

    expect(stages).toHaveLength(3);
    expect(stages[0]).toMatchObject({ type: "pipeline_start", task_type: "generate" });
    expect(stages[1]).toMatchObject({ type: "stage", stage: "retrieval", status: "started" });
    expect(stages[2]).toMatchObject({ type: "stage", stage: "retrieval", status: "succeeded", elapsed_ms: 12 });
    // No non-standard chunks reached the SDK stream.
    for (const c of chunks) {
      expect((c as { type: string }).type).not.toMatch(/^data-/);
    }
  });

  it("restores the type for legacy backend wires that omit it inside data", async () => {
    // Regression for R10-③可视化消失: the old encoder consumed the inner
    // type (data carried only {seq, stage, status}) — the transport must
    // derive it from the outer data- prefixed key so useStageProgress
    // (which dispatches on event.type) keeps working.
    const stages: StageEvent[] = [];
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      sseResponse([
        'data: {"type":"data-pipeline_start","data":{"seq":1,"task_type":"generate"}}\n\n',
        'data: {"type":"data-stage","data":{"seq":2,"stage":"draft","status":"started"}}\n\n',
        "data: [DONE]\n\n",
      ]) as unknown as Response,
    );

    const transport = new PerfChatTransport({
      api: "https://test.local/v1/chat",
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

    expect(stages[0]).toMatchObject({ type: "pipeline_start" });
    expect(stages[1]).toMatchObject({ type: "stage", stage: "draft", status: "started" });
  });

  it("forwards data-perf to onPerf and text-delta to SDK chunks", async () => {
    const perf: PipelinePerf[] = [];
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      sseResponse([
        'data: {"type":"text-delta","delta":"第一段"}\n\n',
        'data: {"type":"text-delta","delta":"第二段"}\n\n',
        'data: {"type":"data-perf","data":{"draft_ms":100}}\n\n',
        'data: {"type":"text-end"}\n\n',
        "data: [DONE]\n\n",
      ]) as unknown as Response,
    );

    const transport = new PerfChatTransport({
      api: "https://test.local/v1/chat",
      onPerf: (p) => perf.push(p),
    });

    const stream = await transport.sendMessages({
      trigger: "submit-message",
      chatId: "t",
      messageId: undefined,
      messages: [],
      abortSignal: undefined,
    });
    const reader = stream.getReader();
    const chunks: Array<{ type: string; delta?: string }> = [];
    for (;;) {
      const r = await reader.read();
      if (r.done) break;
      chunks.push(r.value as { type: string; delta?: string });
    }

    expect(perf).toEqual([{ draft_ms: 100 }]);
    const deltas = chunks.filter((c) => c.type === "text-delta");
    expect(deltas.map((c) => c.delta)).toEqual(["第一段", "第二段"]);
    expect(chunks.some((c) => c.type === "text-start")).toBe(true);
    expect(chunks.some((c) => c.type === "text-end")).toBe(true);
  });

  it("sends messages + extraBody in the request body", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(sseResponse(["data: [DONE]\n\n"]) as unknown as Response);

    const transport = new PerfChatTransport({
      api: "https://test.local/v1/chat",
      onPerf: () => {},
      extraBody: () => ({ chapter_index: 2, total_chapters: 10 }),
    });

    await transport.sendMessages({
      trigger: "submit-message",
      chatId: "t",
      messageId: undefined,
      messages: [{ id: "m1", role: "user", parts: [{ type: "text", text: "写第一章" }] }] as never,
      abortSignal: undefined,
    });

    const body = JSON.parse((fetchSpy.mock.calls[0]?.[1] as RequestInit).body as string);
    expect(body.messages).toEqual([{ role: "user", content: "写第一章" }]);
    expect(body.chapter_index).toBe(2);
    expect(body.total_chapters).toBe(10);
  });

  it("surfaces error events as SDK error chunks", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      sseResponse([
        'data: {"type":"error","detail":"内容被供应商安全审核拦截"}\n\n',
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
    const chunks: Array<{ type: string; errorText?: string }> = [];
    for (;;) {
      const r = await reader.read();
      if (r.done) break;
      chunks.push(r.value as { type: string; errorText?: string });
    }
    const err = chunks.find((c) => c.type === "error");
    expect(err?.errorText).toContain("安全审核");
  });
});
