/**
 * Outline entity extraction — sends the outline to the backend `extract`
 * task (via /v1/chat) and parses the structured JSON result into
 * characters / world settings / plot events.
 */
import {
  ApiError,
  type ExtractEntitiesResult,
  type TaskType,
} from "@/lib/types";
import { chatEndpoint } from "@/lib/config";
import { loadProviderConfig, ownerAuthHeaders } from "@/lib/settings";

const EXTRACT_TASK: TaskType = "extract";

/**
 * Extract the first top-level JSON object from a model reply.
 * Models sometimes wrap JSON in markdown fences or prose; sometimes they
 * emit several JSON objects. A naive indexOf("{")..lastIndexOf("}") breaks
 * on nested braces or trailing prose, so walk braces with a depth counter.
 */
function extractJsonObject(text: string): string {
  const start = text.indexOf("{");
  if (start < 0) return text;
  let depth = 0;
  let inString = false;
  let escape = false;
  for (let i = start; i < text.length; i++) {
    const ch = text[i];
    if (inString) {
      if (escape) escape = false;
      else if (ch === "\\") escape = true;
      else if (ch === '"') inString = false;
      continue;
    }
    if (ch === '"') {
      inString = true;
    } else if (ch === "{") {
      depth++;
    } else if (ch === "}") {
      depth--;
      if (depth === 0) return text.slice(start, i + 1);
    }
  }
  // Unbalanced (model cut off) — fall back to the full remaining text.
  return text.slice(start);
}

function parseExtractJson(text: string): ExtractEntitiesResult {
  // Strip any markdown fences / leading prose the model may add.
  const cleaned = text
    .replace(/^```(?:json)?\s*/m, "")
    .replace(/\s*```$/, "")
    .trim();
  let data: Partial<ExtractEntitiesResult>;
  try {
    data = JSON.parse(extractJsonObject(cleaned)) as Partial<ExtractEntitiesResult>;
  } catch {
    // Last resort: the model replied with prose (JSON mode unsupported).
    // Try to salvage any JSON fragment before giving up.
    const frag = cleaned.match(/\{[\s\S]*\}/)?.[0] ?? "";
    data = frag ? (JSON.parse(frag) as Partial<ExtractEntitiesResult>) : {};
  }
  return {
    characters: Array.isArray(data.characters) ? data.characters : [],
    world_settings: Array.isArray(data.world_settings) ? data.world_settings : [],
    plot_events: Array.isArray(data.plot_events) ? data.plot_events : [],
  };
}

export async function extractEntitiesFromOutline(
  outlineText: string,
): Promise<ExtractEntitiesResult> {
  const cfg = loadProviderConfig();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...ownerAuthHeaders(),
  };
  if (cfg) headers["X-Provider-Config"] = JSON.stringify(cfg);

  const prompt = `[task:${EXTRACT_TASK}] 从以下小说大纲中提取角色、世界观设定和剧情事件。\n\n${outlineText}`;

  const res = await fetch(chatEndpoint, {
    method: "POST",
    headers,
    body: JSON.stringify({
      messages: [{ role: "user", content: prompt }],
    }),
  });

  if (!res.ok) {
    throw new ApiError(`提取失败 (${res.status})`, res.status);
  }

  // Response is a Vercel AI SDK v5 UI Message Stream (SSE). Accumulate
  // text-delta payloads and parse the final text as JSON.
  const text = await res.text();
  const deltas: string[] = [];
  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed.startsWith("data:")) continue;
    const payload = trimmed.slice(5).trim();
    if (!payload || payload === "[DONE]") continue;
    try {
      const parsed = JSON.parse(payload);
      if (parsed.type === "text-delta" && typeof parsed.delta === "string") {
        deltas.push(parsed.delta);
      } else if (
        Array.isArray(parsed.delta) &&
        parsed.delta[0] &&
        typeof parsed.delta[0].text === "string"
      ) {
        deltas.push(parsed.delta[0].text);
      }
    } catch {
      // ignore non-JSON SSE lines
    }
  }

  const full = deltas.join("");
  if (!full.trim()) {
    throw new ApiError("提取未返回任何内容，请检查 API Key 配置或重试", 500);
  }
  return parseExtractJson(full);
}
