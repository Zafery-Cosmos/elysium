import { create } from "zustand";
import { engine, toHumanMessage } from "../services/engine";
import type { Agent, AgentCreate, AgentPermissions } from "../types/engine";
import type { LoadStatus } from "./projects";

/** Clé stable d'un agent pour les mutations (rôle en priorité, sinon id/nom). */
export function agentKey(agent: Agent): string {
  return agent.role ?? agent.id ?? agent.name;
}

interface AgentsState {
  agents: Agent[];
  status: LoadStatus;
  error: string | null;
  /** Clé de l'agent en cours de mutation (toggle / permissions / suppression). */
  mutatingKey: string | null;
  creating: boolean;
  actionError: string | null;
  fetch: () => Promise<void>;
  setEnabled: (agent: Agent, enabled: boolean) => Promise<void>;
  updatePermissions: (
    agent: Agent,
    permissions: AgentPermissions,
  ) => Promise<void>;
  createAgent: (data: AgentCreate) => Promise<boolean>;
  remove: (agent: Agent) => Promise<void>;
}

function patchAgent(
  agents: Agent[],
  key: string,
  patch: Partial<Agent>,
): Agent[] {
  return agents.map((a) => (agentKey(a) === key ? { ...a, ...patch } : a));
}

export const useAgentsStore = create<AgentsState>((set, get) => ({
  agents: [],
  status: "idle",
  error: null,
  mutatingKey: null,
  creating: false,
  actionError: null,

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

  setEnabled: async (agent, enabled) => {
    const key = agentKey(agent);
    const role = agent.role ?? key;
    // Optimiste : la carte réagit immédiatement.
    set({
      mutatingKey: key,
      actionError: null,
      agents: patchAgent(get().agents, key, { enabled }),
    });
    try {
      await engine.updateAgent(role, { enabled });
      set({ mutatingKey: null });
    } catch (err) {
      set({
        mutatingKey: null,
        actionError: toHumanMessage(err),
        agents: patchAgent(get().agents, key, { enabled: !enabled }),
      });
    }
  },

  updatePermissions: async (agent, permissions) => {
    const key = agentKey(agent);
    const role = agent.role ?? key;
    const previous = agent.permissions;
    set({
      mutatingKey: key,
      actionError: null,
      agents: patchAgent(get().agents, key, { permissions }),
    });
    try {
      await engine.updateAgent(role, { permissions });
      set({ mutatingKey: null });
    } catch (err) {
      set({
        mutatingKey: null,
        actionError: toHumanMessage(err),
        agents: patchAgent(get().agents, key, { permissions: previous }),
      });
    }
  },

  createAgent: async (data) => {
    set({ creating: true, actionError: null });
    try {
      await engine.createAgent(data);
      // Recharge la liste pour récupérer l'agent tel que persisté par le moteur.
      const agents = await engine.listAgents().catch(() => null);
      set({
        creating: false,
        ...(agents !== null ? { agents, status: "ready" as LoadStatus } : {}),
      });
      return true;
    } catch (err) {
      set({ creating: false, actionError: toHumanMessage(err) });
      return false;
    }
  },

  remove: async (agent) => {
    const key = agentKey(agent);
    const target = agent.id ?? agent.role ?? key;
    set({ mutatingKey: key, actionError: null });
    try {
      await engine.deleteAgent(target);
      set({
        mutatingKey: null,
        agents: get().agents.filter((a) => agentKey(a) !== key),
      });
    } catch (err) {
      set({ mutatingKey: null, actionError: toHumanMessage(err) });
    }
  },
}));
