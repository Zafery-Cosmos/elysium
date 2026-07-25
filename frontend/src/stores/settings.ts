import { create } from "zustand";
import { persist } from "zustand/middleware";
import { engine } from "../services/engine";
import type { Effort } from "../types/engine";

export type Language = "fr" | "en" | "es";
export type Theme = "light" | "dark" | "auto";
export type Density = "comfortable" | "compact";
export type Motion = "auto" | "on" | "reduced";
export type LogLevel = "error" | "warn" | "info" | "debug";
export type CacheTtl = "5m" | "1h";

/** Réglages persistés localement et synchronisés (au mieux) avec le moteur. */
export interface Settings {
  // Général
  language: Language;
  theme: Theme;
  density: Density;
  motion: Motion;
  // Intelligence artificielle
  defaultProvider: string | null;
  defaultModel: string | null;
  defaultEffort: Effort;
  autoRouting: boolean;
  /** Garde-fou de coût en € par session, null = illimité. */
  costGuard: number | null;
  // Cache de prompt
  cacheEnabled: boolean;
  cacheTtl: CacheTtl;
  // Développeur
  logLevel: LogLevel;
  exposeRawEvents: boolean;
  showLiveCost: boolean;
  // Confidentialité & permissions
  redactSecrets: boolean;
  localOnly: boolean;
}

export const DEFAULT_SETTINGS: Settings = {
  language: "fr",
  theme: "light",
  density: "comfortable",
  motion: "auto",
  defaultProvider: null,
  defaultModel: null,
  defaultEffort: "medium",
  autoRouting: true,
  costGuard: null,
  cacheEnabled: true,
  cacheTtl: "5m",
  logLevel: "warn",
  exposeRawEvents: false,
  showLiveCost: false,
  redactSecrets: true,
  localOnly: false,
};

interface SettingsState extends Settings {
  /** Horodatage du dernier enregistrement (pour l'indicateur « Enregistré »). */
  savedAt: number | null;
  set: <K extends keyof Settings>(key: K, value: Settings[K]) => void;
  syncFromEngine: () => Promise<void>;
}

/* ————— Application des effets sur le document ————— */

function applyToDocument(s: Settings): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;

  // Densité : mise à l'échelle globale via la taille de police racine (rem).
  root.dataset.density = s.density;
  root.style.fontSize = s.density === "compact" ? "15px" : "";

  // Thème : le clair reste la référence visuelle ; le jeton est posé pour un
  // futur mode sombre. On garde color-scheme cohérent avec le rendu clair.
  root.dataset.theme = s.theme;

  // Animations : classe qui prime sur / renforce prefers-reduced-motion.
  root.classList.remove("motion-force", "motion-reduce");
  if (s.motion === "on") root.classList.add("motion-force");
  else if (s.motion === "reduced") root.classList.add("motion-reduce");
}

/* ————— Synchronisation moteur (tolérante) ————— */

const KEYS = Object.keys(DEFAULT_SETTINGS) as Array<keyof Settings>;

/** Ne conserve d'une charge inconnue que les clés au type attendu. */
function pickKnown(payload: unknown): Partial<Settings> {
  if (typeof payload !== "object" || payload === null) return {};
  const record = payload as Record<string, unknown>;
  const out: Partial<Settings> = {};
  for (const key of KEYS) {
    const incoming = record[key];
    const expected = DEFAULT_SETTINGS[key];
    if (incoming === null && (key === "costGuard" || key === "defaultProvider" || key === "defaultModel")) {
      (out as Record<string, unknown>)[key] = null;
    } else if (typeof incoming === typeof expected && incoming !== undefined) {
      (out as Record<string, unknown>)[key] = incoming;
    }
  }
  return out;
}

let patchTimer: ReturnType<typeof setTimeout> | null = null;
let pendingPatch: Partial<Settings> = {};

/** Envoi différé et non bloquant vers PATCH /settings (échec ignoré). */
function schedulePatch(patch: Partial<Settings>): void {
  pendingPatch = { ...pendingPatch, ...patch };
  if (patchTimer !== null) clearTimeout(patchTimer);
  patchTimer = setTimeout(() => {
    const body = pendingPatch;
    pendingPatch = {};
    patchTimer = null;
    void engine.updateSettings(body).catch(() => {
      // Le moteur peut ne pas exposer /settings : réglages locaux conservés.
    });
  }, 400);
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set, get) => ({
      ...DEFAULT_SETTINGS,
      savedAt: null,

      set: (key, value) => {
        set({ [key]: value, savedAt: Date.now() } as Partial<SettingsState>);
        applyToDocument(get());
        schedulePatch({ [key]: value } as Partial<Settings>);
      },

      syncFromEngine: async () => {
        const remote = await engine.getSettings().catch(() => null);
        if (remote === null) return;
        const known = pickKnown(remote);
        if (Object.keys(known).length === 0) return;
        set(known as Partial<SettingsState>);
        applyToDocument(get());
      },
    }),
    {
      name: "elysium-settings",
      onRehydrateStorage: () => (state) => {
        if (state) applyToDocument(state);
      },
    },
  ),
);

/** Applique les effets au démarrage (avant tout rendu dépendant du DOM). */
export function bootstrapSettings(): void {
  applyToDocument(useSettingsStore.getState());
}
