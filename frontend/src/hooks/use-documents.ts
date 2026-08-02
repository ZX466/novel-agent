"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  createDocument,
  deleteDocument,
  getDocument,
  listDocuments,
  updateDocument,
} from "@/lib/documents";
import { ApiError, type DocumentInput, type EditorDoc, type EditorDocListItem } from "@/lib/types";

export type SaveState = "idle" | "saving" | "saved" | "error";

interface UseDocumentsReturn {
  docs: EditorDocListItem[];
  activeDoc: EditorDoc | null;
  listLoading: boolean;
  listError: string | null;
  activeLoading: boolean;
  activeError: string | null;
  saveState: SaveState;
  refreshList: () => Promise<void>;
  selectDoc: (id: number) => Promise<void>;
  resetActive: () => void;
  saveExisting: (doc: EditorDoc, body: DocumentInput) => Promise<void>;
  saveNew: (body: DocumentInput) => Promise<void>;
  removeDoc: (id: number) => Promise<void>;
}

function toListItem(doc: EditorDoc): EditorDocListItem {
  return {
    id: doc.id,
    title: doc.title,
    version: doc.version,
    updated_at: doc.updated_at,
    doc_type: doc.doc_type,
    category: doc.category,
    status: doc.status,
    cover_url: doc.cover_url,
    word_count: doc.word_count,
  };
}

function sortByUpdatedDesc(items: EditorDocListItem[]): EditorDocListItem[] {
  return [...items].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
}

export function useDocuments(): UseDocumentsReturn {
  const [docs, setDocs] = useState<EditorDocListItem[]>([]);
  const [activeDoc, setActiveDoc] = useState<EditorDoc | null>(null);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);
  const [activeLoading, setActiveLoading] = useState(false);
  const [activeError, setActiveError] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Cleanup pending timeouts on unmount to prevent memory leaks.
  useEffect(() => {
    return () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    };
  }, []);

  const refreshList = useCallback(async () => {
    setListLoading(true);
    setListError(null);
    try {
      const r = await listDocuments();
      setDocs(sortByUpdatedDesc(r.items));
    } catch (e) {
      setListError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setListLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshList();
  }, [refreshList]);

  const selectDoc = useCallback(async (id: number) => {
    setActiveLoading(true);
    setActiveError(null);
    try {
      const d = await getDocument(id);
      setActiveDoc(d);
    } catch (e) {
      setActiveError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setActiveLoading(false);
    }
  }, []);

  const resetActive = useCallback(() => {
    setActiveDoc(null);
    setActiveError(null);
  }, []);

  const saveExisting = useCallback(
    async (doc: EditorDoc, body: DocumentInput) => {
      setSaveState("saving");
      try {
        const updated = await updateDocument(doc.id, body);
        setActiveDoc(updated);
        setDocs((prev) =>
          sortByUpdatedDesc(
            prev.map((d) => (d.id === updated.id ? toListItem(updated) : d)),
          ),
        );
        setSaveState("saved");
        if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
        saveTimerRef.current = setTimeout(() => setSaveState("idle"), 1500);
      } catch (e) {
        setSaveState("error");
        throw e;
      }
    },
    [],
  );

  const saveNew = useCallback(async (body: DocumentInput) => {
    setSaveState("saving");
    try {
      const created = await createDocument(body);
      setActiveDoc(created);
      setDocs((prev) => sortByUpdatedDesc([toListItem(created), ...prev]));
      setSaveState("saved");
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
      saveTimerRef.current = setTimeout(() => setSaveState("idle"), 1500);
    } catch (e) {
      setSaveState("error");
      throw e;
    }
  }, []);

  const removeDoc = useCallback(
    async (id: number) => {
      const prev = docs;
      // Optimistic: remove first, rollback on error.
      setDocs((d) => d.filter((x) => x.id !== id));
      if (activeDoc?.id === id) {
        setActiveDoc(null);
      }
      try {
        await deleteDocument(id);
      } catch (e) {
        setDocs(prev);
        // 404 means it was already gone on the server — that's fine.
        if (e instanceof ApiError && e.status === 404) return;
        throw e;
      }
    },
    [docs, activeDoc],
  );

  return {
    docs,
    activeDoc,
    listLoading,
    listError,
    activeLoading,
    activeError,
    saveState,
    refreshList,
    selectDoc,
    resetActive,
    saveExisting,
    saveNew,
    removeDoc,
  };
}
