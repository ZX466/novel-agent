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

/**
 * Enumerate candidate top-level `{...}` regions in text order, skipping
 * braces inside strings and nested objects (brace-depth aware). Each `{`
 * starts a candidate; the caller tries them in order until JSON.parse works,
 * so prose like "注意：{这不是JSON}" is skipped in favour of the real object.
 */
function extractJsonRegions(text: string): string[] {
  const regions: string[] = [];
  for (let start = 0; start < text.length; start++) {
    if (text[start] !== "{") continue;
    let depth = 0;
    let inString = false;
    let escaped = false;
    for (let i = start; i < text.length; i++) {
      const c = text[i];
      if (inString) {
        if (escaped) escaped = false;
        else if (c === "\\") escaped = true;
        else if (c === '"') inString = false;
        continue;
      }
      if (c === '"') inString = true;
      else if (c === "{") depth += 1;
      else if (c === "}") {
        depth -= 1;
        if (depth === 0) {
          regions.push(text.slice(start, i + 1));
          break;
        }
      }
    }
  }
  return regions;
}

function tryParse(raw: string): unknown | null {
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

/**
 * True when the parsed object looks like a Creative Kit (carries at least one
 * of the kit's top-level arrays/fields). Used to skip "legal JSON but not a
 * kit" objects (e.g. prose wrapped in braces) while scanning candidates.
 */
function isKitShape(data: unknown): boolean {
  const rec = asRecord(data);
  return (
    Array.isArray(rec.world_settings) ||
    Array.isArray(rec.characters) ||
    typeof rec.outline === "string"
  );
}

export function parseCreativeKit(text: string): CreativeKitPackage {
  const trimmed = text.trim();
  if (!trimmed) return EMPTY_KIT;

  // Prefer a fenced ```json block; otherwise try candidate {...} regions in
  // order until one parses AND has a kit shape (brace-depth aware, prose-brace
  // tolerant, skips legal-but-unrelated JSON objects).
  let data: unknown | null = null;
  const fence = trimmed.match(/```(?:json)?\s*([\s\S]*?)```/);
  if (fence) {
    data = tryParse(fence[1].trim());
    if (!isKitShape(data)) data = null;
  }
  if (data === null) {
    for (const region of extractJsonRegions(trimmed)) {
      const cand = tryParse(region);
      if (cand !== null && isKitShape(cand)) {
        data = cand;
        break;
      }
    }
  }
  if (data === null) return EMPTY_KIT;
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
