"use client";

/**
 * 交稿雷达 (R6-3, safety radar) dialog state: open/close, rescan, and the
 * export-preflight handshake with the ExportMenu (findings hold the export
 * until the author confirms).
 */
import { useCallback, useState } from "react";

import { fetchSafetyScan, type SafetyScanReport } from "@/lib/safety";
import { downloadExport, type ExportFormat } from "@/lib/export";

interface UseSafetyRadarOpts {
  docId: number | null;
}

export function useSafetyRadar(opts: UseSafetyRadarOpts) {
  const { docId } = opts;
  const [radarOpen, setRadarOpen] = useState(false);
  const [radarReport, setRadarReport] = useState<SafetyScanReport | null>(null);
  const [radarLoading, setRadarLoading] = useState(false);
  const [radarError, setRadarError] = useState<string | null>(null);
  const [pendingExportFmt, setPendingExportFmt] = useState<ExportFormat | null>(null);

  const runSafetyScan = useCallback(async () => {
    if (docId == null) return;
    setRadarLoading(true);
    setRadarError(null);
    try {
      const report = await fetchSafetyScan(docId);
      setRadarReport(report);
    } catch (e) {
      setRadarError(e instanceof Error ? e.message : "安全检查失败");
    } finally {
      setRadarLoading(false);
    }
  }, [docId]);

  const handleOpenRadar = useCallback(() => {
    setPendingExportFmt(null);
    setRadarReport(null);
    setRadarError(null);
    setRadarOpen(true);
    void runSafetyScan();
  }, [runSafetyScan]);

  // Export-menu preflight callback: findings → open radar, hold the format.
  const handleRadarPreflight = useCallback((report: SafetyScanReport, fmt: ExportFormat) => {
    setPendingExportFmt(fmt);
    setRadarReport(report);
    setRadarOpen(true);
  }, []);

  const handleContinueExport = useCallback(async () => {
    if (docId == null || !pendingExportFmt) return;
    try {
      await downloadExport(docId, pendingExportFmt);
    } catch (e) {
      alert(`❌ 导出失败: ${e instanceof Error ? e.message : "未知错误"}`);
    } finally {
      setPendingExportFmt(null);
      setRadarOpen(false);
    }
  }, [docId, pendingExportFmt]);

  const closeRadar = useCallback(() => {
    setPendingExportFmt(null);
    setRadarOpen(false);
  }, []);

  const radarStatus: "idle" | "scanning" | "clean" | "warn" = radarLoading
    ? "scanning"
    : radarReport
      ? radarReport.findings.length > 0
        ? "warn"
        : "clean"
      : "idle";

  return {
    radarOpen, radarReport, radarLoading, radarError,
    pendingExportFmt, radarStatus, runSafetyScan,
    handleOpenRadar, handleRadarPreflight, handleContinueExport, closeRadar,
  };
}
