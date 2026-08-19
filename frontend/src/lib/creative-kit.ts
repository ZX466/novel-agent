/**
 * Creative Kit (R7-2): parse the LLM-generated world-building package into
 * structured rows that map onto existing world_settings / characters / outline.
 *
 * The model is asked to emit a JSON object shaped like `CreativeKitPackage`;
 * this parser tolerantly extracts it from streamed text (fenced ```json blocks
 * or the first top-level `{...}` region) and drops malformed entries.
 */

export interface CreativeKitWorldSetting {
  title: string;
  category?: string;
  content_text: string;
}

export interface CreativeKitCharacter {
  name: string;
  role?: string;
  description?: string;
  attributes?: Record<string, unknown>;
  arc_summary?: string;
}

export interface CreativeKitPackage {
  world_settings: CreativeKitWorldSetting[];
  characters: CreativeKitCharacter[];
  outline: string;
}

export const EMPTY_KIT: CreativeKitPackage = {
  world_settings: [],
  characters: [],
  outline: "",
};

function asRecord(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" ? (v as Record<string, unknown>) : {};
}

export function parseCreativeKit(text: string): CreativeKitPackage {
  const trimmed = text.trim();
  if (!trimmed) return EMPTY_KIT;

  // Prefer a fenced ```json block; otherwise the first {...} region.
  let jsonText = "";
  const fence = trimmed.match(/```(?:json)?\s*([\s\S]*?)```/);
  if (fence) {
    jsonText = fence[1].trim();
  } else {
    const start = trimmed.indexOf("{");
    const end = trimmed.lastIndexOf("}");
    if (start !== -1 && end > start) jsonText = trimmed.slice(start, end + 1);
  }
  if (!jsonText) return EMPTY_KIT;

  let data: unknown;
  try {
    data = JSON.parse(jsonText);
  } catch {
    return EMPTY_KIT;
  }
  const rec = asRecord(data);

  const world_settings: CreativeKitWorldSetting[] = Array.isArray(rec.world_settings)
    ? rec.world_settings.flatMap((w) => {
        const r = asRecord(w);
        const title = typeof r.title === "string" ? r.title.trim() : "";
        if (!title) return [];
        return [
          {
            title,
            category: typeof r.category === "string" ? r.category : undefined,
            content_text:
              typeof r.content_text === "string" ? r.content_text : "",
          },
        ];
      })
    : [];

  const characters: CreativeKitCharacter[] = Array.isArray(rec.characters)
    ? rec.characters.flatMap((c) => {
        const r = asRecord(c);
        const name = typeof r.name === "string" ? r.name.trim() : "";
        if (!name) return [];
        return [
          {
            name,
            role: typeof r.role === "string" ? r.role : undefined,
            description:
              typeof r.description === "string" ? r.description : undefined,
            attributes:
              r.attributes && typeof r.attributes === "object"
                ? (r.attributes as Record<string, unknown>)
                : undefined,
            arc_summary:
              typeof r.arc_summary === "string" ? r.arc_summary : undefined,
          },
        ];
      })
    : [];

  return {
    world_settings,
    characters,
    outline: typeof rec.outline === "string" ? rec.outline : "",
  };
}
