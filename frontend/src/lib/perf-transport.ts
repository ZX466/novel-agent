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
    const TEXT_ID = "text-0";
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
                      controller.enqueue({ type: "text-start", id: TEXT_ID });
                      textStarted = true;
                    }
                    controller.enqueue({
                      type: "text-delta",
                      id: TEXT_ID,
                      delta: String(evt.delta ?? ""),
                    });
                    break;
                  }
                  case "text-end":
                    controller.enqueue({ type: "text-end", id: TEXT_ID });
                    break;
                  case "perf":
                    onPerf((evt.data ?? {}) as PipelinePerf);
                    break;
                  case "stage":
                  case "pipeline_start": {
                    // R9-② stage events: forward to the optional sink.
                    // Unknown/missing sink → ignored (M2 tolerance).
                    if (onStage) onStage(evt as unknown as StageEvent);
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
            controller.enqueue({ type: "text-end", id: TEXT_ID });
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
