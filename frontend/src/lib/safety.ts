/**
 * 交稿雷达 (R6-3) — pre-export safety preflight API client.
 *
 * Backend: GET /v1/documents/{id}/safety-scan — advisory and non-blocking;
 * results are cached server-side by content hash. PII evidence is masked.
 */
import { ApiError } from "@/lib/types";
import { backendUrl } from "@/lib/config";
import { ownerAuthHeaders } from "@/lib/settings";

export type SafetySeverity = "INFO" | "WARNING" | "BLOCK";

export interface SafetyFinding {
  rule_name: string;
  category: string;
  severity: SafetySeverity;
  description: string;
  count: number;
  sample: string;
}

export interface SafetyScanSummary {
  matched_count: number;
  max_severity: SafetySeverity;
  should_block: boolean;
  by_category: Record<string, string[]>;
}

export interface SafetyScanReport {
  doc_id: number;
  content_hash: string;
  cached: boolean;
  truncated: boolean;
  rules_checked: number;
  scanned_at: string | null;
  summary: SafetyScanSummary;
  findings: SafetyFinding[];
}

export async function fetchSafetyScan(docId: number): Promise<SafetyScanReport> {
  const res = await fetch(`${backendUrl}/v1/documents/${docId}/safety-scan`, {
    headers: { ...ownerAuthHeaders() },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail: unknown;
    try {
      const body = await res.json();
      detail = body?.detail ?? body;
    } catch {
      // non-JSON error body
    }
    const msg =
      typeof detail === "string"
        ? detail
        : detail && typeof detail === "object" && "detail" in (detail as object)
          ? String((detail as { detail: unknown }).detail)
          : `安全检查失败 (${res.status})`;
    throw new ApiError(msg, res.status, detail);
  }
  return (await res.json()) as SafetyScanReport;
}