import { create } from "zustand";
import { engine, toHumanMessage } from "../services/engine";
import type { Agent } from "../types/engine";
import type { LoadStatus } from "./projects";

interface AgentsState {
  agents: Agent[];
  status: LoadStatus;
  error: string | null;
  fetch: () => Promise<void>;
}

export const useAgentsStore = create<AgentsState>((set, get) => ({
  agents: [],
  status: "idle",
  error: null,

  fetch: async () => {
    if (get().status === "loading") return;
    set({ status: "loading", error: null });
    try {
      const agents = await engine.listAgents();
      set({ agents, status: "ready" });
    } catch (err) {
      set({ status: "error", error: toHumanMessage(err) });
    }
  },
}));
