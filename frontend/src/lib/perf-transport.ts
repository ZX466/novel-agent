"use client";

import type { ChatTransport, ChatRequestOptions, UIMessage, UIMessageChunk } from "ai";

export interface PipelinePerf {
  retrieval_ms?: number;
  draft_ms?: number;
  refine_ms?: number;
  evaluate_ms?: number;
  safety_ms?: number;
  [stage: string]: number | undefined;
}

/** R9-② stage event payload (protocol v1, codex 480d802). */
export interface StageEvent {
  type: "stage" | "pipeline_start";
  stage?: string;
  status?: "started" | "succeeded" | "failed" | "skipped";
  iteration?: number;
  elapsed_ms?: number;
  code?: string;
  reason?: string;
  seq?: number;
  summary?: Record<string, unknown>;
}

/** PerfPulse: custom ChatTransport that parses the backend SSE stream
 *  directly, so non-AI-SDK custom events (e.g. `{"type":"perf",...}`)
 *  can be captured without being dropped by DefaultChatTransport's
 *  uiMessageChunkSchema validation.
 *
 *  Wire format (backend app/api/chat.py): `data: {json}\n\n`, terminated
 *  by `data: [DONE]\n\n`. Text chunks are translated into AI SDK
 *  UIMessageChunk objects; perf chunks are passed to `onPerf`.
 */
export class PerfChatTransport implements ChatTransport<UIMessage> {
  private readonly base: string;
  private readonly headers: () => Record<string, string>;
  private readonly onPerf: (perf: PipelinePerf) => void;
  private readonly onStage?: (event: StageEvent) => void;
  /** R9-④⑥: extra structured body fields (chapter_index etc.), resolved
   *  per send so closures over fresh state are honored. */
  private readonly extraBody?: () => Record<string, unknown>;

  constructor(opts: {
    api: string;
    headers?: () => Record<string, string>;
    onPerf: (perf: PipelinePerf) => void;
    /** R9-② optional stage-event sink; absent = events ignored (M2 tolerance). */
    onStage?: (event: StageEvent) => void;
    /** R9-④⑥ optional extra request-body fields (chapter_* / target_word_count). */
    extraBody?: () => Record<string, unknown>;
  }) {
    this.base = opts.api;
    this.headers = opts.headers ?? (() => ({}));
    this.onPerf = opts.onPerf;
    this.onStage = opts.onStage;
    this.extraBody = opts.extraBody;
  }

  async sendMessages(opts: {
    trigger: "submit-message" | "regenerate-message";
    chatId: string;
    messageId: string | undefined;
    messages: UIMessage[];
    abortSignal: AbortSignal | undefined;
  } & ChatRequestOptions): Promise<ReadableStream<UIMessageChunk>> {
    // Build the request the same shape as DefaultChatTransport expects:
    // the chat API accepts an OpenAI-style message array.
    const body = {
      messages: opts.messages.map((m) => ({
        role: m.role,
        content: m.parts
          .filter((p) => p.type === "text" && "text" in p)
          .map((p) => (p as { text: string }).text)
          .join("\n"),
      })),
      ...(this.extraBody?.() ?? {}),
    };

    const res = await fetch(this.base, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...this.headers(),
      },
      body: JSON.stringify(body),
      signal: opts.abortSignal,
    });

    if (!res.ok || !res.body) {
      const detail = await res.text().catch(() => "");
      throw new Error(`Chat request failed (${res.status}): ${detail}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let textStarted = false;
    // 09-15: generate 全链上 draft(初稿)与 refine(润色稿)都通过 on_token
    // 流进同一个 SSE 文本流。若把它们拼进同一个 text part,面板会显示
    // "初稿+润色稿"拼接体(实测:同一段故事写两遍,4286字)。收到
    // refine 阶段开始时,结束当前 part 并开新 part——useChat 的 parts
    // 数组里最后一个 text part 即最终稿,消费方(面板/插入)取它即可。
    let partIndex = 0;
    const partId = () => `text-${partIndex}`;
    const onPerf = this.onPerf; // capture (avoid `this` inside stream callbacks)
    const onStage = this.onStage;

    const stream = new ReadableStream<UIMessageChunk>({
      async start(controller) {
        try {
          for (;;) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            // SSE events separated by blank line.
            let sep: number;
            while ((sep = buffer.indexOf("\n\n")) >= 0) {
              const raw = buffer.slice(0, sep);
              buffer = buffer.slice(sep + 2);
              for (const line of raw.split("\n")) {
                if (!line.startsWith("data:")) continue;
                const payload = line.slice(5).trim();
                if (payload === "[DONE]") {
                  if (textStarted) {
                    controller.enqueue({ type: "text-end", id: partId() });
                  }
                  controller.close();
                  return;
                }
                let evt: Record<string, unknown>;
                try {
                  evt = JSON.parse(payload);
                } catch {
                  continue;
                }
                switch (evt.type) {
                  case "text-delta": {
                    if (!textStarted) {
                      controller.enqueue({ type: "text-start", id: partId() });
                      textStarted = true;
                    }
                    controller.enqueue({
                      type: "text-delta",
                      id: partId(),
                      delta: String(evt.delta ?? ""),
                    });
                    break;
                  }
                  case "text-end":
                    // 后端在 [DONE] 前会发一次收尾 text-end(chat.py
                    // _encode_text_end)。只在确实有打开的 part 时转发,
                    // 并把 textStarted 复位——否则 [DONE] 分支的兜底会再
                    // 发一次同 id text-end,AI SDK 的 activeTextParts[id]
                    // 已被删除,二次 end 抛 "Cannot set properties of
                    // undefined (setting 'state')"(09-15 用户报告)。
                    if (textStarted) {
                      controller.enqueue({ type: "text-end", id: partId() });
                      textStarted = false;
                    }
                    break;
                  case "data-perf":
                    // Backend wraps perf as a data- prefixed part (AI SDK v5
                    // strict chunk schema rejects bare unknown types).
                    onPerf((evt.data ?? {}) as PipelinePerf);
                    break;
                  case "data-stage":
                  case "data-pipeline_start": {
                    // R9-② stage events: backend wraps the payload as
                    // `{"type":"data-stage","data":{…}}` — unwrap before
                    // forwarding to the sink. The backend's wrapper consumes
                    // the original `type` key (chat.py _encode_custom_event
                    // pops it), so restore it from the outer wire type.
                    // Unknown/missing sink → ignored (M2 tolerance).
                    if (onStage) {
                      const inner = (evt.data ?? {}) as Record<string, unknown>;
                      const restored = {
                        type: String(evt.type).slice(5), // "data-stage" → "stage"
                        ...inner,
                      } as unknown as StageEvent;
                      onStage(restored);
                    }
                    // 09-15 多阶段分段: refine 开始 = 初稿已被润色稿取代。
                    // 结束当前 part、开新 part;后一个 part 在 UI parts 数组
                    // 里排后,消费方取最后一个 text part 即最终稿。只在
                    // 已有打开的 part 时切(避免 refine 先于任何文本时产生
                    // 空 part);iteration>0(evaluate 回炉)不切——同一份
                    // 润色稿的重跑不该再多开 part。
                    const st = (evt.data ?? {}) as {
                      type?: string; stage?: string; status?: string; iteration?: number;
                    };
                    if (
                      st.type === "stage" &&
                      st.stage === "refine" &&
                      st.status === "started" &&
                      textStarted &&
                      (st.iteration ?? 0) === 0
                    ) {
                      controller.enqueue({ type: "text-end", id: partId() });
                      partIndex += 1;
                      textStarted = false;
                    }
                    break;
                  }
                  case "error":
                    controller.enqueue({
                      type: "error",
                      errorText: String(evt.detail ?? evt.errorText ?? "Pipeline error"),
                    });
                    break;
                  default:
                    // start / start-step / finish-step / finish — no-op chunks
                    break;
                }
              }
            }
          }
          if (textStarted) {
            controller.enqueue({ type: "text-end", id: partId() });
          }
          controller.close();
        } catch (e) {
          controller.error(e);
        }
      },
    });

    return stream;
  }

  async reconnectToStream(_opts: {
    chatId: string;
    abortSignal?: AbortSignal | undefined;
  } & ChatRequestOptions): Promise<ReadableStream<UIMessageChunk> | null> {
    // PerfPulse: no server-side stream persistence — resume is not supported.
    return null;
  }
}
