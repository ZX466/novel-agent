"use client";

import { useEffect, useRef, useState } from "react";

import { backendUrl } from "@/lib/config";
import { useProviderConfig } from "@/hooks/use-provider-config";
import {
  clearApiKey,
  emptyProviderConfig,
  isStageComplete,
  loadApiKey,
  ownerAuthHeaders,
  saveApiKey,
} from "@/lib/settings";
import {
  ALL_STAGE_KEYS,
  BYOK_PRESETS,
  RECOMMENDED_MODELS,
  STAGE_LABELS,
  STAGE_KEYS,
  type AllStageKey,
  type ByokPreset,
  type ProviderConfig,
  type StageConfig,
  type StageKey,
} from "@/lib/types";

interface SettingsDialogProps {
  open: boolean;
  onClose: () => void;
}

const RISK_WARNING = "API Key 仅存储在本机浏览器 localStorage，请勿在公共电脑使用。";

/**
 * Turn a FastAPI error body into a readable message.
 * FastAPI returns `detail` as a string (HTTPException) OR an array of
 * validation-error objects (422). Naive `${detail}` renders "[object Object]".
 */
function describeApiError(data: unknown): string {
  if (data == null) return "";
  if (typeof data === "string") return data;
  if (typeof data !== "object") return String(data);
  const detail = (data as { detail?: unknown }).detail;
  if (detail == null) return JSON.stringify(data);
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object") {
          const loc = (item as { loc?: unknown[] }).loc?.join(".");
          const msg = (item as { msg?: unknown }).msg;
          return loc && msg ? `${loc}: ${msg}` : String(msg ?? "");
        }
        return String(item);
      })
      .filter(Boolean);
    return parts.join("；") || "请求参数错误";
  }
  return JSON.stringify(detail);
}

interface StageFormState {
  api_base: string;
  api_key: string;
  model: string;
  extra_headers_json: string;
}

function stageToForm(stage: StageConfig | undefined | null): StageFormState {
  const extra = stage?.extra_headers ?? {};
  return {
    api_base: stage?.api_base ?? "",
    api_key: stage?.api_key ?? "",
    model: stage?.model ?? "",
    extra_headers_json:
      Object.keys(extra).length > 0 ? JSON.stringify(extra, null, 2) : "",
  };
}

function formToStage(form: StageFormState): {
  stage: StageConfig;
  parseError: string | null;
} {
  let extra_headers: Record<string, string> | undefined;
  if (form.extra_headers_json.trim() !== "") {
    try {
      const parsed = JSON.parse(form.extra_headers_json);
      if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("不是 JSON 对象");
      }
      extra_headers = {};
      for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
        extra_headers[String(k)] = String(v);
      }
    } catch (e) {
      return {
        stage: {
          api_base: form.api_base.trim(),
          api_key: form.api_key.trim(),
          model: form.model.trim(),
        },
        parseError: e instanceof Error ? e.message : "JSON 解析失败",
      };
    }
  }
  return {
    stage: {
      api_base: form.api_base.trim(),
      api_key: form.api_key.trim(),
      model: form.model.trim(),
      extra_headers,
    },
    parseError: null,
  };
}

export function SettingsDialog({ open, onClose }: SettingsDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const apiBaseInputRef = useRef<HTMLInputElement>(null);
  const { config, save, clear } = useProviderConfig();

  const [forms, setForms] = useState<Record<AllStageKey, StageFormState>>({
    draft: stageToForm(null),
    refine: stageToForm(null),
    evaluate: stageToForm(null),
    embedding: stageToForm(null),
  });
  const [expandedStage, setExpandedStage] = useState<AllStageKey | null>("draft");
  // Owner API key sent as X-API-Key on all protected requests (owner_key_hash scope).
  const [apiKey, setApiKey] = useState("");
  const [parseErrors, setParseErrors] = useState<Record<AllStageKey, string | null>>({
    draft: null,
    refine: null,
    evaluate: null,
    embedding: null,
  });
  // Provider-pulled model lists per stage (replaces hardcoded dropdown when non-empty).
  const [fetchedModels, setFetchedModels] = useState<Record<AllStageKey, string[]>>({
    draft: [],
    refine: [],
    evaluate: [],
    embedding: [],
  });

  useEffect(() => {
    if (!open) return;
    const cfg = config ?? emptyProviderConfig();
    setApiKey(loadApiKey());
    setForms({
      draft: stageToForm(cfg.draft),
      refine: stageToForm(cfg.refine),
      evaluate: stageToForm(cfg.evaluate),
      embedding: stageToForm(cfg.embedding),
    });
    setExpandedStage("draft");
    setParseErrors({ draft: null, refine: null, evaluate: null, embedding: null });
  }, [open, config]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open) {
      if (!dialog.open) dialog.showModal();
      requestAnimationFrame(() => apiBaseInputRef.current?.focus());
    } else {
      if (dialog.open) dialog.close();
    }
  }, [open]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const handleClose = () => {
      if (open) onClose();
    };
    dialog.addEventListener("close", handleClose);
    return () => dialog.removeEventListener("close", handleClose);
  }, [open, onClose]);

  // At least one stage must be complete to save; users shouldn't be forced to
  // configure all three chat stages at once.
  const anyStageComplete = STAGE_KEYS.some((k) => {
    const f = forms[k];
    return f.api_base.trim() !== "" && f.api_key.trim() !== "" && f.model.trim() !== "";
  });

  const updateField = (stage: AllStageKey, field: keyof StageFormState, value: string) => {
    setForms((prev) => ({ ...prev, [stage]: { ...prev[stage], [field]: value } }));
    if (parseErrors[stage]) {
      setParseErrors((prev) => ({ ...prev, [stage]: null }));
    }
  };

  const handleSave = () => {
    const next: ProviderConfig = {
      draft: emptyProviderConfig().draft,
      refine: emptyProviderConfig().refine,
      evaluate: emptyProviderConfig().evaluate,
    };
    const newErrors: Record<AllStageKey, string | null> = {
      draft: null,
      refine: null,
      evaluate: null,
      embedding: null,
    };
    for (const k of ALL_STAGE_KEYS) {
      const { stage, parseError } = formToStage(forms[k]);
      newErrors[k] = parseError;
      if (k === "embedding") {
        // Only persist embedding if user actually filled it in.
        if (stage.api_base.trim() && stage.api_key.trim() && stage.model.trim()) {
          next.embedding = stage;
        }
      } else {
        next[k as StageKey] = stage;
      }
    }
    setParseErrors(newErrors);
    if (newErrors.draft || newErrors.refine || newErrors.evaluate || newErrors.embedding) {
      for (const k of ALL_STAGE_KEYS) {
        if (newErrors[k]) {
          setExpandedStage(k);
          break;
        }
      }
      return;
    }
    save(next);
    saveApiKey(apiKey);
    onClose();
  };

  const handleClear = () => {
    clear();
    clearApiKey();
    setApiKey("");
    const blank = stageToForm(null);
    setForms({ draft: blank, refine: blank, evaluate: blank, embedding: blank });
    setParseErrors({ draft: null, refine: null, evaluate: null, embedding: null });
    onClose();
  };

  return (
    <dialog
      ref={dialogRef}
      aria-modal="true"
      aria-labelledby="settings-title"
      className="rounded-lg p-0 w-[min(90vw,580px)] max-h-[85vh] overflow-hidden backdrop:bg-black/60"
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border-hairline)",
        boxShadow: "var(--shadow-lg)",
        color: "var(--fg)",
      }}
    >
      <form
        method="dialog"
        onSubmit={(e) => {
          e.preventDefault();
          handleSave();
        }}
        className="flex flex-col max-h-[85vh]"
      >
        {/* Settings header */}
        <header
          className="px-sp-6 py-sp-5 border-b flex items-center justify-between shrink-0"
          style={{ borderColor: "var(--border-subtle)" }}
        >
          <h2
            id="settings-title"
            className="font-display text-lg font-semibold"
            style={{ color: "var(--fg)", letterSpacing: "-0.01em" }}
          >
            API Provider 设置
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭"
            className="w-[30px] h-[30px] flex items-center justify-center rounded-sm text-xl transition-colors"
            style={{ color: "var(--muted)" }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = "var(--surface-2)";
              e.currentTarget.style.color = "var(--fg)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = "transparent";
              e.currentTarget.style.color = "var(--muted)";
            }}
          >
            ×
          </button>
        </header>

        {/* Settings body */}
        <div className="flex-1 overflow-y-auto px-sp-6 py-sp-5 space-y-sp-5">
          {/* Quick setup presets */}
          <div className="space-y-sp-2">
            <span className="text-[11px] font-semibold" style={{ color: "var(--fg-secondary)" }}>
              快速配置
            </span>
            <div className="grid grid-cols-1 gap-sp-2">
              {BYOK_PRESETS.map((preset) => (
                <button
                  key={preset.key}
                  type="button"
                  onClick={() => {
                    // Apply preset: fill api_base and model, leave api_key empty for user to fill
                    const next = { ...forms };
                    for (const stageKey of STAGE_KEYS) {
                      const presetStage = preset.config[stageKey as keyof typeof preset.config];
                      if (presetStage) {
                        next[stageKey] = {
                          ...next[stageKey],
                          api_base: presetStage.api_base,
                          model: presetStage.model,
                        };
                      }
                    }
                    setForms(next);
                    setExpandedStage("draft");
                  }}
                  className="text-left px-sp-3 py-sp-2 border rounded-md transition-colors"
                  style={{ borderColor: "var(--border)", color: "var(--fg-secondary)" }}
                  onMouseEnter={(e) => { e.currentTarget.style.borderColor = "var(--accent)"; e.currentTarget.style.background = "var(--accent-bg)"; }}
                  onMouseLeave={(e) => { e.currentTarget.style.borderColor = "var(--border)"; e.currentTarget.style.background = "transparent"; }}
                >
                  <span className="text-[12px] font-medium block" style={{ color: "var(--fg)" }}>{preset.label}</span>
                  <span className="text-[10px]" style={{ color: "var(--muted)" }}>{preset.description}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Warning */}
          <div
            className="text-xs p-sp-4 rounded-md leading-relaxed"
            style={{
              color: "var(--warn)",
              background: "oklch(0.74 0.10 85 / 0.06)",
              border: "1px solid oklch(0.74 0.10 85 / 0.12)",
            }}
          >
            {RISK_WARNING}
          </div>

          <p className="text-xs leading-relaxed" style={{ color: "var(--muted)" }}>
            三个聊天阶段为必填；Embedding 阶段为可选（留空则回退到后端 .env 默认配置）。
          </p>

          {/* Owner API key (X-API-Key) — website-level auth, separate from provider keys */}
          <div className="space-y-sp-2">
            <span className="text-[11px] font-semibold" style={{ color: "var(--fg-secondary)" }}>
              网站鉴权 Key（可选）
            </span>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="对应后端 API_KEYS 中的任一 Key"
              autoComplete="off"
              className="w-full px-sp-3 py-sp-2 border rounded-sm text-[13px] font-mono outline-none transition-all"
              style={{
                background: "var(--bg)",
                borderColor: "var(--border)",
                color: "var(--fg)",
              }}
              onFocus={(e) => {
                e.currentTarget.style.borderColor = "var(--accent-muted)";
                e.currentTarget.style.boxShadow = "0 0 0 2px var(--accent-glow)";
              }}
              onBlur={(e) => {
                e.currentTarget.style.borderColor = "var(--border)";
                e.currentTarget.style.boxShadow = "none";
              }}
            />
            <p className="text-[10px] leading-relaxed" style={{ color: "var(--muted)" }}>
              所有受保护接口（作品/章节/角色/设定/检索）会自动携带 X-API-Key。未配置或后端为开放模式时留空即可。
            </p>
          </div>

          {/* Stage accordions */}
          <div className="space-y-sp-3">
            {ALL_STAGE_KEYS.map((stageKey) => {
              const labels = STAGE_LABELS[stageKey];
              const form = forms[stageKey];
              const expanded = expandedStage === stageKey;
              const complete = isStageComplete({
                api_base: form.api_base,
                api_key: form.api_key,
                model: form.model,
              });
              const isOptional = stageKey === "embedding";

              return (
                <div
                  key={stageKey}
                  className="border rounded-md overflow-hidden transition-colors"
                  style={{ borderColor: "var(--border)" }}
                  onMouseEnter={(e) => { e.currentTarget.style.borderColor = "var(--border-hairline)"; }}
                  onMouseLeave={(e) => { e.currentTarget.style.borderColor = "var(--border)"; }}
                >
                  <button
                    type="button"
                    onClick={() => setExpandedStage(expanded ? null : stageKey)}
                    className="w-full flex items-center justify-between px-sp-4 py-sp-3 text-left transition-colors"
                    aria-expanded={expanded}
                    onMouseEnter={(e) => { e.currentTarget.style.background = "var(--surface-2)"; }}
                    onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
                  >
                    <span className="flex items-center gap-sp-3">
                      <span
                        className="text-[9px] w-3 text-center"
                        style={{ color: "var(--muted)" }}
                      >
                        {expanded ? "▼" : "▶"}
                      </span>
                      <span
                        className="text-[13px] font-medium"
                        style={{ color: "var(--fg)", letterSpacing: "-0.01em" }}
                      >
                        {labels.title}
                      </span>
                      {isOptional && (
                        <span
                          className="text-[10px] px-1.5 py-0.5 rounded"
                          style={{
                            background: "oklch(0.74 0.10 85 / 0.08)",
                            color: "var(--warn)",
                          }}
                        >
                          可选
                        </span>
                      )}
                      <span
                        className="w-[5px] h-[5px] rounded-full"
                        style={{ background: complete ? "var(--success)" : "var(--border)" }}
                        title={complete ? "已配置" : "未配置"}
                      />
                    </span>
                    <span
                      className="text-[11px] font-mono truncate max-w-[50%]"
                      style={{ color: "var(--muted)", letterSpacing: "0.02em" }}
                    >
                      {form.model || "未配置"}
                    </span>
                  </button>

                  {expanded && (
                    <div
                      className="px-sp-4 pb-sp-4 space-y-sp-3"
                      style={{ borderTop: "1px solid var(--border-subtle)" }}
                    >
                      <p className="text-[11px] mt-sp-3 leading-relaxed" style={{ color: "var(--muted)" }}>
                        {labels.hint}
                      </p>

                      <FieldGroup label="API Base URL">
                        <input
                          ref={stageKey === "draft" ? apiBaseInputRef : undefined}
                          type="url"
                          value={form.api_base}
                          onChange={(e) => updateField(stageKey, "api_base", e.target.value)}
                          placeholder="https://api.openai.com/v1"
                          className="w-full px-sp-3 py-sp-2 border rounded-sm text-[13px] font-mono outline-none transition-all"
                          style={{
                            background: "var(--bg)",
                            borderColor: "var(--border)",
                            color: "var(--fg)",
                          }}
                          onFocus={(e) => {
                            e.currentTarget.style.borderColor = "var(--accent-muted)";
                            e.currentTarget.style.boxShadow = "0 0 0 2px var(--accent-glow)";
                          }}
                          onBlur={(e) => {
                            e.currentTarget.style.borderColor = "var(--border)";
                            e.currentTarget.style.boxShadow = "none";
                          }}
                        />
                      </FieldGroup>

                      <FieldGroup label="API Key">
                        <input
                          type="password"
                          value={form.api_key}
                          onChange={(e) => updateField(stageKey, "api_key", e.target.value)}
                          placeholder="sk-..."
                          autoComplete="off"
                          className="w-full px-sp-3 py-sp-2 border rounded-sm text-[13px] font-mono outline-none transition-all"
                          style={{
                            background: "var(--bg)",
                            borderColor: "var(--border)",
                            color: "var(--fg)",
                          }}
                          onFocus={(e) => {
                            e.currentTarget.style.borderColor = "var(--accent-muted)";
                            e.currentTarget.style.boxShadow = "0 0 0 2px var(--accent-glow)";
                          }}
                          onBlur={(e) => {
                            e.currentTarget.style.borderColor = "var(--border)";
                            e.currentTarget.style.boxShadow = "none";
                          }}
                        />
                      </FieldGroup>

                      <FieldGroup label="Model Name">
                        <div className="flex gap-sp-2">
                          <input
                            type="text"
                            value={form.model}
                            onChange={(e) => updateField(stageKey, "model", e.target.value)}
                            placeholder="gpt-4o-mini / qwen-max / claude-sonnet-4-5 / ..."
                            className="flex-1 px-sp-3 py-sp-2 border rounded-sm text-[13px] font-mono outline-none transition-all"
                            style={{ background: "var(--bg)", borderColor: "var(--border)", color: "var(--fg)" }}
                            onFocus={(e) => { e.currentTarget.style.borderColor = "var(--accent-muted)"; e.currentTarget.style.boxShadow = "0 0 0 2px var(--accent-glow)"; }}
                            onBlur={(e) => { e.currentTarget.style.borderColor = "var(--border)"; e.currentTarget.style.boxShadow = "none"; }}
                          />
                          <select
                            value=""
                            onChange={(e) => {
                              if (e.target.value) updateField(stageKey, "model", e.target.value);
                            }}
                            className="px-sp-2 py-sp-2 border rounded-sm text-[11px] outline-none"
                            style={{ background: "var(--bg)", borderColor: "var(--border)", color: "var(--muted)", minWidth: "80px" }}
                          >
                            <option value="">{fetchedModels[stageKey].length ? "模型↓" : "推荐↓"}</option>
                            {(fetchedModels[stageKey].length ? fetchedModels[stageKey] : RECOMMENDED_MODELS[stageKey] || []).map((m) => (
                              <option key={m} value={m}>{m}</option>
                            ))}
                          </select>
                          <button
                            type="button"
                            onClick={async () => {
                              const stageForm = forms[stageKey];
                              if (!stageForm.api_base || !stageForm.api_key) {
                                alert("请先填写 API Base 和 API Key，再拉取模型");
                                return;
                              }
                              const btn = document.getElementById(`fetch-models-${stageKey}`);
                              if (btn) { btn.textContent = "拉取中..."; btn.setAttribute("disabled", "true"); }
                              try {
                                const res = await fetch(`${backendUrl}/v1/chat/models`, {
                                  method: "POST",
                                  headers: {
                                    "Content-Type": "application/json",
                                    ...ownerAuthHeaders(),
                                  },
                                  body: JSON.stringify({
                                    api_base: stageForm.api_base.trim(),
                                    api_key: stageForm.api_key.trim(),
                                    extra_headers: stageForm.extra_headers_json.trim()
                                      ? (JSON.parse(stageForm.extra_headers_json) as Record<string, string>)
                                      : undefined,
                                  }),
                                });
                                const data = await res.json();
                                if (!res.ok) {
                                  alert(`❌ 拉取失败: ${describeApiError(data) || `HTTP ${res.status}`}`);
                                  return;
                                }
                                const list: string[] = data.models ?? [];
                                setFetchedModels((prev) => ({ ...prev, [stageKey]: list }));
                                if (list.length) {
                                  alert(`✅ 拉取到 ${list.length} 个模型，已填入下拉列表`);
                                }
                              } catch (err) {
                                alert(`❌ 拉取失败: ${err instanceof Error ? err.message : "网络错误"}`);
                              } finally {
                                if (btn) { btn.textContent = "拉取模型"; btn.removeAttribute("disabled"); }
                              }
                            }}
                            id={`fetch-models-${stageKey}`}
                            title="用当前 API Base + Key 拉取可用模型"
                            className="px-sp-2 py-sp-2 border rounded-sm text-[11px] shrink-0 transition-colors"
                            style={{ borderColor: "var(--border)", color: "var(--accent)" }}
                            onMouseEnter={(e) => { e.currentTarget.style.borderColor = "var(--accent)"; }}
                            onMouseLeave={(e) => { e.currentTarget.style.borderColor = "var(--border)"; }}
                          >
                            拉取模型
                          </button>
                        </div>
                        <span className="text-[10px] mt-0.5 block" style={{ color: "var(--muted)" }}>
                          填纯 model 名，不要带 provider 前缀。点击&ldquo;拉取模型&rdquo;可从 API 自动获取可用列表。
                          {stageKey === "embedding" && " 例如: text-embedding-v4 / text-embedding-3-small"}
                        </span>
                      </FieldGroup>

                      {/* Extra headers toggle */}
                      <div>
                        <button
                          type="button"
                          onClick={() =>
                            setForms((prev) => ({
                              ...prev,
                              [stageKey]: {
                                ...prev[stageKey],
                                extra_headers_json:
                                  prev[stageKey].extra_headers_json.trim() === "" ? "" : prev[stageKey].extra_headers_json,
                              },
                            }))
                          }
                          className="text-[11px] transition-colors"
                          style={{ color: "var(--accent)" }}
                          onMouseEnter={(e) => { e.currentTarget.style.textDecoration = "underline"; }}
                          onMouseLeave={(e) => { e.currentTarget.style.textDecoration = "none"; }}
                          aria-expanded={form.extra_headers_json.trim() !== ""}
                          aria-controls={`extra-headers-${stageKey}`}
                        >
                          {form.extra_headers_json.trim() !== "" ? "▼ 额外请求头（已填写）" : "▶ 额外请求头（可选）"}
                        </button>
                        {form.extra_headers_json.trim() !== "" && (
                          <div id={`extra-headers-${stageKey}`} className="mt-1">
                            <textarea
                              value={form.extra_headers_json}
                              onChange={(e) => updateField(stageKey, "extra_headers_json", e.target.value)}
                              placeholder='{"X-Title": "Project11", "HTTP-Referer": "https://p11.dev"}'
                              rows={3}
                              className="w-full px-sp-3 py-sp-2 border rounded-sm text-xs font-mono outline-none transition-all"
                              style={{
                                background: "var(--bg)",
                                borderColor: "var(--border)",
                                color: "var(--fg)",
                              }}
                              onFocus={(e) => {
                                e.currentTarget.style.borderColor = "var(--accent-muted)";
                                e.currentTarget.style.boxShadow = "0 0 0 2px var(--accent-glow)";
                              }}
                              onBlur={(e) => {
                                e.currentTarget.style.borderColor = "var(--border)";
                                e.currentTarget.style.boxShadow = "none";
                              }}
                            />
                            {parseErrors[stageKey] && (
                              <p className="text-[11px] mt-1" style={{ color: "var(--danger)" }}>
                                JSON 解析错误：{parseErrors[stageKey]}
                              </p>
                            )}
                          </div>
                        )}
                      </div>

                      {/* Connection test */}
                      <button
                        type="button"
                        onClick={async () => {
                          const stageForm = forms[stageKey];
                          if (!stageForm.api_base || !stageForm.api_key || !stageForm.model) {
                            alert("请先填写 API Base、API Key 和 Model");
                            return;
                          }
                          // Set testing state
                          const testBtn = document.getElementById(`test-${stageKey}`);
                          if (testBtn) { testBtn.textContent = "测试中..."; testBtn.setAttribute("disabled", "true"); }
                          try {
                            const { api_base, api_key, model } = stageForm;
                            const res = await fetch(`${backendUrl}/v1/chat/test`, {
                              method: "POST",
                              headers: {
                                "Content-Type": "application/json",
                                ...ownerAuthHeaders(),
                                "X-Provider-Config": JSON.stringify({
                                  draft: { api_base, api_key, model },
                                  refine: { api_base, api_key, model },
                                  evaluate: { api_base, api_key, model },
                                  embedding: { api_base, api_key, model },
                                }),
                              },
                              body: JSON.stringify({ stage: stageKey }),
                            });
                            const data = await res.json();
                            if (res.ok && data.ok) {
                              let msg = `✅ 连接成功！模型: ${data.model || model}`;
                              if (data.detected_dim !== undefined) {
                                msg += `\n向量维度: ${data.detected_dim}`;
                                if (!data.dim_match) {
                                  msg += `\n⚠️ 维度不匹配！模型返回 ${data.detected_dim}，配置期望 ${data.expected_dim}。系统会自动适配，但建议修改 .env 中 EMBEDDING_DIM=${data.detected_dim}`;
                                }
                              }
                              alert(msg);
                            } else {
                              alert(`❌ 连接失败: ${describeApiError(data) || "未知错误"}`);
                            }
                          } catch (err) {
                            alert(`❌ 连接失败: ${err instanceof Error ? err.message : "网络错误"}`);
                          } finally {
                            if (testBtn) { testBtn.textContent = "测试连接"; testBtn.removeAttribute("disabled"); }
                          }
                        }}
                        id={`test-${stageKey}`}
                        className="mt-sp-2 px-sp-3 py-sp-1.5 rounded-sm text-[11px] font-medium border transition-colors"
                        style={{ borderColor: "var(--border)", color: "var(--fg-secondary)" }}
                        onMouseEnter={(e) => { e.currentTarget.style.borderColor = "var(--accent)"; e.currentTarget.style.color = "var(--accent)"; }}
                        onMouseLeave={(e) => { e.currentTarget.style.borderColor = "var(--border)"; e.currentTarget.style.color = "var(--fg-secondary)"; }}
                      >
                        测试连接
                      </button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Settings footer */}
        <footer
          className="px-sp-6 py-sp-4 border-t flex items-center justify-between shrink-0"
          style={{ borderColor: "var(--border-subtle)" }}
        >
          <button
            type="button"
            onClick={handleClear}
            className="text-sm px-sp-3 py-sp-2 rounded-sm transition-colors"
            style={{ color: "var(--danger)" }}
            onMouseEnter={(e) => { e.currentTarget.style.background = "oklch(0.60 0.16 25 / 0.08)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
          >
            清除已保存配置
          </button>
          <div className="flex gap-sp-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm rounded-sm border transition-colors"
              style={{
                borderColor: "var(--border-hairline)",
                color: "var(--fg-secondary)",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = "var(--surface-2)";
                e.currentTarget.style.borderColor = "var(--muted)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = "transparent";
                e.currentTarget.style.borderColor = "var(--border-hairline)";
              }}
            >
              取消
            </button>
            <button
              type="submit"
              disabled={!anyStageComplete}
              className="px-4 py-2 text-sm rounded-sm transition-all disabled:opacity-30 disabled:cursor-not-allowed"
              style={{
                background: "var(--accent)",
                color: "var(--bg)",
              }}
              onMouseEnter={(e) => {
                if (anyStageComplete) {
                  e.currentTarget.style.background = "var(--accent-hover)";
                  e.currentTarget.style.boxShadow = "var(--shadow-glow)";
                }
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = "var(--accent)";
                e.currentTarget.style.boxShadow = "none";
              }}
            >
              保存
            </button>
          </div>
        </footer>
      </form>
    </dialog>
  );
}

function FieldGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <span
        className="text-[10px] font-semibold uppercase"
        style={{ color: "var(--fg-tertiary)", letterSpacing: "0.06em" }}
      >
        {label}
      </span>
      {children}
    </div>
  );
}
