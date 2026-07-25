import { create } from "zustand";
import { engine, toHumanMessage } from "../services/engine";
import type {
  McpCatalogEntry,
  McpServer,
  McpServerInstall,
} from "../types/engine";
import type { LoadStatus } from "./projects";

interface McpState {
  catalog: McpCatalogEntry[];
  servers: McpServer[];
  status: LoadStatus;
  error: string | null;
  /** Identifiant catalogue en cours d'installation ("custom" pour le modal). */
  installing: string | null;
  /** Serveur installé en cours de modification/suppression. */
  mutatingId: string | null;
  actionError: string | null;
  fetch: () => Promise<void>;
  install: (catalogId: string) => Promise<boolean>;
  addCustom: (data: McpServerInstall) => Promise<boolean>;
  setEnabled: (id: string, enabled: boolean) => Promise<void>;
  remove: (id: string) => Promise<void>;
}

async function refreshServers(
  set: (partial: Partial<McpState>) => void,
): Promise<void> {
  const servers = await engine.listMcpServers().catch(() => null);
  if (servers !== null) set({ servers });
}

export const useMcpStore = create<McpState>((set, get) => ({
  catalog: [],
  servers: [],
  status: "idle",
  error: null,
  installing: null,
  mutatingId: null,
  actionError: null,

  fetch: async () => {
    if (get().status === "loading") return;
    set({ status: "loading", error: null });
    try {
      const [catalog, servers] = await Promise.all([
        engine.listMcpCatalog(),
        engine.listMcpServers(),
      ]);
      set({ catalog, servers, status: "ready" });
    } catch (err) {
      set({ status: "error", error: toHumanMessage(err) });
    }
  },

  install: async (catalogId) => {
    set({ installing: catalogId, actionError: null });
    try {
      await engine.installMcpServer({ catalog_id: catalogId });
      await refreshServers(set);
      set({ installing: null });
      return true;
    } catch (err) {
      set({ installing: null, actionError: toHumanMessage(err) });
      return false;
    }
  },

  addCustom: async (data) => {
    set({ installing: "custom", actionError: null });
    try {
      await engine.installMcpServer(data);
      await refreshServers(set);
      set({ installing: null });
      return true;
    } catch (err) {
      set({ installing: null, actionError: toHumanMessage(err) });
      return false;
    }
  },

  setEnabled: async (id, enabled) => {
    set({ mutatingId: id, actionError: null });
    // Optimiste : l'interrupteur répond immédiatement.
    set({
      servers: get().servers.map((s) => (s.id === id ? { ...s, enabled } : s)),
    });
    try {
      await engine.updateMcpServer(id, { enabled });
      set({ mutatingId: null });
    } catch (err) {
      set({
        mutatingId: null,
        actionError: toHumanMessage(err),
        servers: get().servers.map((s) =>
          s.id === id ? { ...s, enabled: !enabled } : s,
        ),
      });
    }
  },

  remove: async (id) => {
    set({ mutatingId: id, actionError: null });
    try {
      await engine.removeMcpServer(id);
      set({
        mutatingId: null,
        servers: get().servers.filter((s) => s.id !== id),
      });
    } catch (err) {
      set({ mutatingId: null, actionError: toHumanMessage(err) });
    }
  },
}));
