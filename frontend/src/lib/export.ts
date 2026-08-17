/**
 * Export download helper — triggers a browser download of a novel document.
 *
 * Backend: GET /v1/documents/{id}/export?format=md|txt|epub (Round 4, kilo domain).
 */
import { ApiError } from "@/lib/types";
import { backendUrl } from "@/lib/config";
import { ownerAuthHeaders } from "@/lib/settings";

export type ExportFormat = "md" | "txt" | "epub";

export const EXPORT_LABELS: Record<ExportFormat, string> = {
  md: "Markdown",
  txt: "纯文本 TXT",
  epub: "EPUB",
};

export async function downloadExport(docId: number, format: ExportFormat): Promise<void> {
  const res = await fetch(`${backendUrl}/v1/documents/${docId}/export?format=${format}`, {
    headers: { ...ownerAuthHeaders() },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail: unknown;
    try {
      const body = await res.json();
      detail = body?.detail ?? body;
    } catch {
      // non-JSON body
    }
    const msg =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((d) => String((d as { msg?: unknown }).msg ?? "")).filter(Boolean).join("；") || `HTTP ${res.status}`
          : `HTTP ${res.status}`;
    throw new ApiError(msg, res.status, detail);
  }

  const blob = await res.blob();
  // Prefer RFC 5987 filename from Content-Disposition, else a safe default.
  const cd = res.headers.get("Content-Disposition") ?? "";
  const match = /filename\*=UTF-8''([^;]+)/.exec(cd);
  const filename = match
    ? decodeURIComponent(match[1]).replace(/[\\/:*?"<>|]/g, "_")
    : `novel-${docId}.${format}`;

  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
