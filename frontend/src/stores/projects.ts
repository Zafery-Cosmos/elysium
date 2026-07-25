import { create } from "zustand";
import { engine, toHumanMessage } from "../services/engine";
import type { Project, ProjectCreate } from "../types/engine";

export type LoadStatus = "idle" | "loading" | "ready" | "error";

interface ProjectsState {
  projects: Project[];
  status: LoadStatus;
  error: string | null;
  creating: boolean;
  fetch: () => Promise<void>;
  create: (data: ProjectCreate) => Promise<Project | null>;
}

export const useProjectsStore = create<ProjectsState>((set, get) => ({
  projects: [],
  status: "idle",
  error: null,
  creating: false,

  fetch: async () => {
    if (get().status === "loading") return;
    set({ status: "loading", error: null });
    try {
      const projects = await engine.listProjects();
      set({ projects, status: "ready" });
    } catch (err) {
      set({ status: "error", error: toHumanMessage(err) });
    }
  },

  create: async (data) => {
    set({ creating: true });
    try {
      const project = await engine.createProject(data);
      set((state) => ({
        projects: [project, ...state.projects],
        creating: false,
        status: "ready",
      }));
      return project;
    } catch (err) {
      set({ creating: false, error: toHumanMessage(err) });
      return null;
    }
  },
}));
