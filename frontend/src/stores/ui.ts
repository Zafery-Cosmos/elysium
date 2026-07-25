import { create } from "zustand";
import { persist } from "zustand/middleware";

export type UiMode = "simple" | "advanced";

interface UiState {
  sidebarCollapsed: boolean;
  mode: UiMode;
  toggleSidebar: () => void;
  setMode: (mode: UiMode) => void;
}

export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      mode: "simple",
      toggleSidebar: () =>
        set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
      setMode: (mode) => set({ mode }),
    }),
    { name: "elysium-ui" },
  ),
);
