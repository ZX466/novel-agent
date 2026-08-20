/**
 * Shared frontend types — documents, chapters, characters, world settings,
 * plot events, BYOK provider config, and AI pipeline task routing.
 *
 * Field shapes mirror the backend Pydantic schemas (backend/app/schemas/).
 */

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(message: string, status: number, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

// ---------------------------------------------------------------------------
// Work types / categories
// ---------------------------------------------------------------------------

export type WorkTypeTabKey =
  | "all"
  | "novel"
  | "short"
  | "script"
  | "video"
  | "trash";

export const WORK_TYPE_TABS: Array<{ key: WorkTypeTabKey; label: string }> = [
  { key: "all", label: "全部" },
  { key: "novel", label: "小说" },
  { key: "short", label: "短篇" },
  { key: "script", label: "剧本" },
  { key: "video", label: "视频" },
  { key: "trash", label: "回收站" },
];

export const DOC_TYPE_CATEGORY_MAP: Record<string, string> = {
  novel: "长篇",
  short: "短篇",
  script: "剧本",
  video: "视频",
};

export interface DocumentListFilters {
  limit?: number;
  offset?: number;
  type?: string;
  category?: string;
  search?: string;
  status?: "active" | "deleted";
}

// ---------------------------------------------------------------------------
// Documents
// ---------------------------------------------------------------------------

/** List-item shape returned by GET /v1/documents (no content). */
export interface EditorDocListItem {
  id: number;
  title: string;
  version: number;
  doc_type: string;
  category: string;
  status: string;
  cover_url: string;
  word_count: number;
  updated_at: string;
}

/** Full document shape returned by GET /v1/documents/{id}. */
export interface EditorDoc {
  id: number;
  title: string;
  content_html: string;
  content_text: string;
  version: number;
  doc_type: string;
  category: string;
  metadata_json: Record<string, unknown>;
  status: string;
  cover_url: string;
  word_count: number;
  created_at: string;
  updated_at: string;
}

/** Body for creating a new document (POST /v1/documents). */
export interface DocumentInput {
  title: string;
  content_html?: string;
  content_text?: string;
  doc_type?: string;
  category?: string;
  metadata_json?: Record<string, unknown>;
  cover_url?: string;
}

/** Body for partial update of an existing document (PATCH /v1/documents/{id}). */
export interface DocumentPartial {
  title?: string;
  content_html?: string;
  content_text?: string;
  doc_type?: string;
  category?: string;
  metadata_json?: Record<string, unknown>;
  cover_url?: string;
  /** When true, the server PATCH-merges metadata_json instead of replacing it
   *  (used by editor-save / Creative Kit flows so concurrent writes don't
   *  clobber unrelated keys like `outline`). */
  merge_metadata?: boolean;
}

// ---------------------------------------------------------------------------
// Chapters
// ---------------------------------------------------------------------------

export interface ChapterListItem {
  id: number;
  novel_id: number;
  chapter_index: number;
  title: string;
  content_text: string;
  summary: string;
  word_count: number;
  status: string;
  metadata_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ChapterRead extends ChapterListItem {}

export interface ChapterInput {
  chapter_index?: number;
  title?: string;
  content_text?: string;
  summary?: string;
  metadata_json?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Chapter snapshots (R5-4 安心回溯)
// ---------------------------------------------------------------------------

/** A point-in-time copy of a chapter's text (snapshots API). */
export interface ChapterSnapshot {
  id: number;
  chapter_id: number;
  title: string;
  content_text: string;
  word_count: number;
  reason: string;
  created_at: string;
}

/** Paginated snapshot list returned by GET .../snapshots. */
export interface SnapshotListResponse {
  items: ChapterSnapshot[];
  total: number;
}

/** Canonical auto-snapshot triggers (matches backend SNAPSHOT_REASONS). */
export const SNAPSHOT_REASONS = [
  "save",
  "insert",
  "replace",
  "export",
  "manual",
] as const;

export type SnapshotReason = (typeof SNAPSHOT_REASONS)[number];

/** Human-readable label for each snapshot trigger. */
export const SNAPSHOT_REASON_LABELS: Record<SnapshotReason, string> = {
  save: "保存",
  insert: "AI 插入",
  replace: "替换",
  export: "导出",
  manual: "手动",
};

// ---------------------------------------------------------------------------
// Characters
// ---------------------------------------------------------------------------

export interface CharacterListItem {
  id: number;
  novel_id: number;
  name: string;
  role: string;
  description: string;
  attributes: Record<string, unknown>;
  arc_summary: string;
  created_at: string;
  updated_at: string;
}

export interface CharacterRead extends CharacterListItem {}

export interface CharacterUpdate {
  name?: string;
  role?: string;
  description?: string;
  attributes?: Record<string, unknown>;
  arc_summary?: string;
}

export const CHARACTER_ROLE_OPTIONS = [
  "主角",
  "配角",
  "反派",
  "其他",
];

// ---------------------------------------------------------------------------
// World settings
// ---------------------------------------------------------------------------

export interface WorldSettingListItem {
  id: number;
  novel_id: number;
  category: string;
  title: string;
  content_text: string;
  metadata_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface WorldSettingRead extends WorldSettingListItem {}

export interface WorldSettingCreate {
  category?: string;
  title: string;
  content_text?: string;
  metadata_json?: Record<string, unknown>;
}

export const WORLD_CATEGORY_OPTIONS = [
  "地理",
  "势力",
  "体系",
  "其他",
];

// ---------------------------------------------------------------------------
// Plot events
// ---------------------------------------------------------------------------

export interface PlotEventListItem {
  id: number;
  novel_id: number;
  chapter_id: number | null;
  chapter_index: number | null;
  event_type: string;
  summary: string;
  involved_character_ids: number[];
  created_at: string;
  updated_at: string;
}

export interface PlotEventRead extends PlotEventListItem {}

export const PLOT_EVENT_TYPE_OPTIONS = [
  "起",
  "承",
  "转",
  "合",
  "高潮",
  "结局",
  "其他",
];

// ---------------------------------------------------------------------------
// AI pipeline task routing
// ---------------------------------------------------------------------------

export type TaskType =
  | "generate"
  | "continue"
  | "rewrite"
  | "polish"
  | "outline"
  | "extract";

// ---------------------------------------------------------------------------
// BYOK provider configuration (three chat stages + optional embedding)
// ---------------------------------------------------------------------------

export type StageKey = "draft" | "refine" | "evaluate";
export type AllStageKey = StageKey | "embedding";

export interface StageConfig {
  api_base: string;
  api_key: string;
  model: string;
  extra_headers?: Record<string, string>;
}

export interface ProviderConfig {
  draft: StageConfig;
  refine: StageConfig;
  evaluate: StageConfig;
  embedding?: StageConfig | null;
}

export const STAGE_KEYS: StageKey[] = ["draft", "refine", "evaluate"];

export const ALL_STAGE_KEYS: AllStageKey[] = [
  "draft",
  "refine",
  "evaluate",
  "embedding",
];

export const STAGE_LABELS: Record<
  AllStageKey,
  { title: string; hint: string }
> = {
  draft: {
    title: "草稿",
    hint: "低成本生成初稿，使用 DeepSeek-V4-Flash 或 gpt-4o-mini 等。",
  },
  refine: {
    title: "精修",
    hint: "中文编辑能力强，使用 Qwen-Max 或 gpt-4o 等。",
  },
  evaluate: {
    title: "评估",
    hint: "推理稳定，T=0，使用 Claude Sonnet 或 gpt-4o 等。",
  },
  embedding: {
    title: "向量嵌入",
    hint: "用于 RAG 记忆检索，需支持 /embeddings 接口的模型。",
  },
};

export interface ByokPresetStage {
  api_base: string;
  model: string;
}

export interface ByokPreset {
  key: string;
  label: string;
  description: string;
  config: Partial<Record<AllStageKey, ByokPresetStage>>;
}

export const BYOK_PRESETS: ByokPreset[] = [
  {
    key: "recommended",
    label: "推荐：DeepSeek + Qwen + Claude",
    description: "草稿 DeepSeek / 精修 Qwen / 评估 Claude，中文写作首选",
    config: {
      draft: {
        api_base: "https://api.deepseek.com/v1",
        model: "deepseek-v4-flash",
      },
      refine: {
        api_base: "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model: "qwen-max",
      },
      evaluate: {
        api_base: "https://api.claude.com/v1",
        model: "claude-sonnet-4-5",
      },
    },
  },
  {
    key: "openai",
    label: "全 OpenAI",
    description: "三阶段全部使用 OpenAI GPT 系列",
    config: {
      draft: { api_base: "https://api.openai.com/v1", model: "gpt-4o-mini" },
      refine: { api_base: "https://api.openai.com/v1", model: "gpt-4o" },
      evaluate: { api_base: "https://api.openai.com/v1", model: "gpt-4o" },
    },
  },
  {
    key: "dashscope",
    label: "全 DashScope",
    description: "三阶段全部使用阿里云通义千问",
    config: {
      draft: {
        api_base: "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model: "qwen-plus",
      },
      refine: {
        api_base: "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model: "qwen-max",
      },
      evaluate: {
        api_base: "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model: "qwen-max",
      },
    },
  },
];

export const RECOMMENDED_MODELS: Record<AllStageKey, string[]> = {
  draft: ["deepseek-v4-flash", "gpt-4o-mini", "qwen-plus"],
  refine: ["qwen-max", "gpt-4o", "deepseek-v4"],
  evaluate: ["claude-sonnet-4-5", "gpt-4o", "qwen-max"],
  embedding: ["text-embedding-3-small", "text-embedding-v4", "bge-m3"],
};

// ---------------------------------------------------------------------------
// Outline entity extraction result
// ---------------------------------------------------------------------------

export interface ExtractedCharacter {
  name: string;
  role?: string;
  description?: string;
  arc_summary?: string;
}

export interface ExtractedWorldSetting {
  category?: string;
  title: string;
  content_text?: string;
}

export interface ExtractedPlotEvent {
  chapter_index?: number | null;
  event_type?: string;
  summary: string;
}

export interface ExtractEntitiesResult {
  characters: ExtractedCharacter[];
  world_settings: ExtractedWorldSetting[];
  plot_events: ExtractedPlotEvent[];
}
