import { create } from "zustand";
import { persist } from "zustand/middleware";

export type UiMode = "simple" | "advanced";

/** Connexion « compte personnel » via un CLI officiel (pas de clé API). */
export type CliProvider = "claude-code" | "codex";

interface UiState {
  sidebarCollapsed: boolean;
  mode: UiMode;
  /** Page de bienvenue du premier démarrage déjà passée ou terminée. */
  onboardingDone: boolean;
  /** Fournisseur CLI choisi à l'accueil (null = passé). */
  preferredCli: CliProvider | null;
  /** Tutoriel interactif terminé ou passé (il s'ouvre une fois après la connexion). */
  tourDone: boolean;
  completeTour: () => void;
  restartTour: () => void;
  /** Dernier projet ouvert (réglage « reprendre la dernière conversation »). */
  lastProjectId: string | null;
  setLastProject: (id: string | null) => void;
  toggleSidebar: () => void;
  setMode: (mode: UiMode) => void;
  completeOnboarding: (cli?: CliProvider) => void;
}

export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      mode: "simple",
      onboardingDone: false,
      preferredCli: null,
      tourDone: false,
      completeTour: () => set({ tourDone: true }),
      restartTour: () => set({ tourDone: false }),
      lastProjectId: null,
      setLastProject: (id) => set({ lastProjectId: id }),
      toggleSidebar: () =>
        set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
      setMode: (mode) => set({ mode }),
      completeOnboarding: (cli) =>
        set({ onboardingDone: true, preferredCli: cli ?? null }),
    }),
    { name: "elysium-ui" },
  ),
);
