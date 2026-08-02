"use client";

/** React hook wrapper around the BYOK ProviderConfig localStorage helpers.
 *
 * Returns `loaded` so callers can avoid hydration mismatches: SSR and the
 * first client render see `config=null, loaded=false`; after mount, the hook
 * reads localStorage and flips `loaded=true`. Use `loaded` to gate any UI
 * that depends on the configured/unconfigured distinction.
 *
 * `isConfigured` is true only when ALL THREE stages (draft/refine/evaluate)
 * have api_base / api_key / model filled. Partial config is treated as
 * unconfigured so the user is prompted to finish setup.
 */

import { useCallback, useEffect, useState } from "react";

import {
  clearProviderConfig,
  isProviderConfigComplete,
  loadProviderConfig,
  saveProviderConfig,
} from "@/lib/settings";
import type { ProviderConfig } from "@/lib/types";

export interface UseProviderConfigReturn {
  config: ProviderConfig | null;
  isConfigured: boolean;
  loaded: boolean;
  save: (cfg: ProviderConfig) => void;
  clear: () => void;
}

export function useProviderConfig(): UseProviderConfigReturn {
  const [config, setConfig] = useState<ProviderConfig | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    setConfig(loadProviderConfig());
    setLoaded(true);
  }, []);

  const save = useCallback((cfg: ProviderConfig) => {
    saveProviderConfig(cfg);
    setConfig(cfg);
  }, []);

  const clear = useCallback(() => {
    clearProviderConfig();
    setConfig(null);
  }, []);

  return {
    config,
    isConfigured: isProviderConfigComplete(config),
    loaded,
    save,
    clear,
  };
}
