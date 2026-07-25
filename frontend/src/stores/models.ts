import { create } from "zustand";
import { engine, toHumanMessage } from "../services/engine";
import type { ProviderConfig, ProviderInfo } from "../types/engine";
import type { LoadStatus } from "./projects";

interface ModelsState {
  providers: ProviderInfo[];
  status: LoadStatus;
  error: string | null;
  savingProvider: string | null;
  saveError: string | null;
  fetch: () => Promise<void>;
  configure: (name: string, config: ProviderConfig) => Promise<boolean>;
}

export const useModelsStore = create<ModelsState>((set, get) => ({
  providers: [],
  status: "idle",
  error: null,
  savingProvider: null,
  saveError: null,

  fetch: async () => {
    if (get().status === "loading") return;
    set({ status: "loading", error: null });
    try {
      const providers = await engine.listModels();
      set({ providers, status: "ready" });
    } catch (err) {
      set({ status: "error", error: toHumanMessage(err) });
    }
  },

  configure: async (name, config) => {
    set({ savingProvider: name, saveError: null });
    try {
      await engine.configureProvider(name, config);
      set({ savingProvider: null });
      // Rafraîchit le statut configuré/joignable après enregistrement.
      const providers = await engine.listModels().catch(() => null);
      if (providers !== null) set({ providers, status: "ready" });
      return true;
    } catch (err) {
      set({ savingProvider: null, saveError: toHumanMessage(err) });
      return false;
    }
  },
}));
