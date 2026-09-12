"use client";

/**
 * Page-level dialogs (交稿雷达 / 版本历史 / 灵感套件), grouped so the editor
 * page keeps only layout. Version-history restore loads the snapshot text as
 * HTML and marks the doc dirty; Creative Kit's onApplied refreshes the parent
 * document copy so a later save never overwrites the applied outline with a
 * stale metadata_json (P0 fix).
 */
import { CreativeKitDialog } from "@/components/CreativeKitDialog";
import { VersionHistoryDialog } from "@/components/VersionHistoryDialog";
import { SafetyScanDialog } from "@/components/SafetyScanDialog";
import { textToTipTapHTML } from "@/lib/insert-text";
import type { Editor as TiptapEditor } from "@tiptap/react";
import type { EditorDoc } from "@/lib/types";
import type { SafetyScanReport } from "@/lib/safety";
import type { ExportFormat } from "@/lib/export";

interface EditorDialogsProps {
  docId: number;
  editor: TiptapEditor | null;
  // Radar
  radarOpen: boolean;
  radarReport: SafetyScanReport | null;
  radarLoading: boolean;
  radarError: string | null;
  pendingExportFmt: ExportFormat | null;
  onCloseRadar: () => void;
  onContinueExport: () => void;
  onRescan: () => void;
  // History
  historyOpen: boolean;
  onCloseHistory: () => void;
  activeChapterId: number | null;
  activeChapterTitle: string | null;
  currentText: string;
  // Creative Kit
  kitOpen: boolean;
  onCloseKit: () => void;
  onKitApplied: (updated: EditorDoc) => void;
}

export function EditorDialogs(props: EditorDialogsProps) {
  const {
    docId, editor,
    radarOpen, radarReport, radarLoading, radarError, pendingExportFmt,
    onCloseRadar, onContinueExport, onRescan,
    historyOpen, onCloseHistory, activeChapterId, activeChapterTitle, currentText,
    kitOpen, onCloseKit, onKitApplied,
  } = props;

  return (
    <>
      {/* 交稿雷达 (R6-3) dialog */}
      <SafetyScanDialog
        open={radarOpen}
        report={radarReport}
        loading={radarLoading}
        error={radarError}
        pendingExport={pendingExportFmt}
        onClose={onCloseRadar}
        onContinueExport={onContinueExport}
        onRescan={onRescan}
      />

      {/* Version history dialog */}
      <VersionHistoryDialog
        open={historyOpen}
        docId={docId}
        chapterId={activeChapterId}
        chapterTitle={activeChapterTitle ?? ""}
        currentText={currentText}
        onClose={onCloseHistory}
        onRestore={(text) => {
          if (editor) {
            editor.chain().setContent(textToTipTapHTML(text), false).run();
          }
        }}
      />

      {/* Creative Kit dialog (R7-2) */}
      <CreativeKitDialog
        docId={docId}
        open={kitOpen}
        onClose={onCloseKit}
        onApplied={onKitApplied}
      />
    </>
  );
}
