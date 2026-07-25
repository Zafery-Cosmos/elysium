import { create } from "zustand";
import { engine, toHumanMessage } from "../services/engine";
import type {
  CustomProviderCreate,
  ProviderConfig,
  ProviderInfo,
  ProviderTestResult,
} from "../types/engine";
import type { LoadStatus } from "./projects";

interface ModelsState {
  providers: ProviderInfo[];
  status: LoadStatus;
  error: string | null;
  savingProvider: string | null;
  saveError: string | null;
  /** Fournisseur en cours de test de connexion (POST /test). */
  testingProvider: string | null;
  /** Dernier résultat de test par fournisseur. */
  testResults: Record<string, ProviderTestResult>;
  addingCustom: boolean;
  addCustomError: string | null;
  fetch: () => Promise<void>;
  configure: (name: string, config: ProviderConfig) => Promise<boolean>;
  test: (name: string) => Promise<void>;
  addCustom: (data: CustomProviderCreate) => Promise<boolean>;
}

export const useModelsStore = create<ModelsState>((set, get) => ({
  providers: [],
  status: "idle",
  error: null,
  savingProvider: null,
  saveError: null,
  testingProvider: null,
  testResults: {},
  addingCustom: false,
  addCustomError: null,

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

  test: async (name) => {
    set({ testingProvider: name });
    try {
      const result = await engine.testProvider(name);
      set((state) => ({
        testingProvider: null,
        testResults: { ...state.testResults, [name]: result },
      }));
    } catch (err) {
      set((state) => ({
        testingProvider: null,
        testResults: {
          ...state.testResults,
          [name]: { reachable: false, detail: toHumanMessage(err) },
        },
      }));
    }
  },

  addCustom: async (data) => {
    set({ addingCustom: true, addCustomError: null });
    try {
      await engine.addProvider(data);
      set({ addingCustom: false });
      const providers = await engine.listModels().catch(() => null);
      if (providers !== null) set({ providers, status: "ready" });
      return true;
    } catch (err) {
      set({ addingCustom: false, addCustomError: toHumanMessage(err) });
      return false;
    }
  },
}));
