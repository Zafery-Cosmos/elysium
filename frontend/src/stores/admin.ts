import { create } from "zustand";
import { engine, toHumanMessage } from "../services/engine";
import type { AdminOverview } from "../types/engine";
import type { LoadStatus } from "./projects";

export type AdminPeriod = 7 | 30 | 90;

interface AdminState {
  overview: AdminOverview | null;
  status: LoadStatus;
  error: string | null;
  days: AdminPeriod;
  setDays: (days: AdminPeriod) => void;
  /** `silent` : rafraîchissement en arrière-plan, sans repasser en chargement. */
  fetch: (silent?: boolean) => Promise<void>;
}

export const useAdminStore = create<AdminState>((set, get) => ({
  overview: null,
  status: "idle",
  error: null,
  days: 30,

  setDays: (days) => {
    set({ days });
    void get().fetch();
  },

  fetch: async (silent = false) => {
    if (!silent) set({ status: "loading", error: null });
    const requested = get().days;
    try {
      const overview = await engine.adminOverview(requested);
      if (get().days !== requested) return; // période changée entre-temps
      set({ overview, status: "ready", error: null });
    } catch (err) {
      // En rafraîchissement silencieux, on garde les dernières données affichées.
      if (silent && get().overview !== null) return;
      set({ status: "error", error: toHumanMessage(err) });
    }
  },
}));
