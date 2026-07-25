import { create } from "zustand";
import { persist } from "zustand/middleware";
import { engine } from "../services/engine";
import type { ChatMode, Effort, Execution } from "../types/engine";

export type Language = "fr" | "en" | "es";
export type Theme = "light" | "dark" | "auto";
export type Density = "comfortable" | "compact";
export type Motion = "auto" | "on" | "reduced";
export type FontSize = "small" | "normal" | "large";
export type AiLanguage = "auto" | "fr" | "en" | "es";
export type LogLevel = "error" | "warn" | "info" | "debug";
export type CacheTtl = "5m" | "1h" | "24h";
export type ApprovalScope = "none" | "privileged" | "all";
export type ContextSize = "small" | "balanced" | "large" | "max";

/** Réglages persistés localement et synchronisés (au mieux) avec le moteur. */
export interface Settings {
  // ————— Général —————
  language: Language;
  theme: Theme;
  density: Density;
  motion: Motion;
  fontSize: FontSize;
  resumeLastConversation: boolean;
  confirmBeforeDelete: boolean;
  aiResponseLanguage: AiLanguage;

  // ————— Intelligence artificielle —————
  defaultProvider: string | null;
  defaultModel: string | null;
  defaultEffort: Effort;
  defaultExecution: Execution;
  defaultMode: ChatMode;
  autoRouting: boolean;
  /** Garde-fou de coût en € par session, null = illimité. */
  costGuard: number | null;
  /** Plafond de tokens en réponse, null = automatique. */
  maxResponseTokens: number | null;
  streaming: boolean;
  /** Délai d'expiration d'une requête, en secondes. */
  requestTimeout: number;
  maxRetries: number;
  multiModelCompare: boolean;
  autoFallback: boolean;

  // ————— Cache de prompt —————
  cacheEnabled: boolean;
  cacheTtl: CacheTtl;
  /** Taille minimale de préfixe mise en cache, en tokens. */
  cacheMinPrefix: number;
  cacheWarmup: boolean;
  cacheStatsVisible: boolean;

  // ————— Agents & permissions —————
  allowDebates: boolean;
  maxParallelAgents: number;
  humanApproval: ApprovalScope;
  autoSnapshot: boolean;

  // ————— Contexte & mémoire —————
  vectorMemory: boolean;
  contextSize: ContextSize;
  autoCompaction: boolean;
  autoSummary: boolean;

  // ————— Développeur —————
  logLevel: LogLevel;
  exposeRawEvents: boolean;
  showLiveCost: boolean;
  /** Port du moteur, null = géré par l'application. */
  enginePort: number | null;
  devtools: boolean;

  // ————— Confidentialité —————
  redactSecrets: boolean;
  localOnly: boolean;
  telemetry: boolean;
  clearOnQuit: boolean;
  encryption: boolean;
}

export const DEFAULT_SETTINGS: Settings = {
  language: "fr",
  theme: "light",
  density: "comfortable",
  motion: "auto",
  fontSize: "normal",
  resumeLastConversation: true,
  confirmBeforeDelete: true,
  aiResponseLanguage: "auto",

  defaultProvider: null,
  defaultModel: null,
  defaultEffort: "medium",
  defaultExecution: "simple",
  defaultMode: "discuss",
  autoRouting: true,
  costGuard: null,
  maxResponseTokens: null,
  streaming: true,
  requestTimeout: 120,
  maxRetries: 2,
  multiModelCompare: false,
  autoFallback: true,

  cacheEnabled: true,
  cacheTtl: "5m",
  cacheMinPrefix: 1024,
  cacheWarmup: false,
  cacheStatsVisible: false,

  allowDebates: true,
  maxParallelAgents: 3,
  humanApproval: "privileged",
  autoSnapshot: true,

  vectorMemory: true,
  contextSize: "balanced",
  autoCompaction: true,
  autoSummary: true,

  logLevel: "warn",
  exposeRawEvents: false,
  showLiveCost: false,
  enginePort: null,
  devtools: false,

  redactSecrets: true,
  localOnly: false,
  telemetry: false,
  clearOnQuit: false,
  encryption: true,
};

interface SettingsState extends Settings {
  /** Horodatage du dernier enregistrement (pour l'indicateur « Enregistré »). */
  savedAt: number | null;
  set: <K extends keyof Settings>(key: K, value: Settings[K]) => void;
  syncFromEngine: () => Promise<void>;
}

/* ————— Application des effets sur le document ————— */

const FONT_PX: Record<FontSize, number> = {
  small: 14.5,
  normal: 16,
  large: 17.5,
};

function applyToDocument(s: Settings): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;

  // Densité : posée en attribut pour d'éventuels ajustements d'espacement.
  root.dataset.density = s.density;

  // Taille de police racine (rem) : combine taille choisie et densité
  // (le mode compact resserre d'un point).
  const px = FONT_PX[s.fontSize] - (s.density === "compact" ? 1 : 0);
  root.style.fontSize = `${String(px)}px`;

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

const NULLABLE_STRING = new Set<keyof Settings>([
  "defaultProvider",
  "defaultModel",
]);
const NULLABLE_NUMBER = new Set<keyof Settings>([
  "costGuard",
  "maxResponseTokens",
  "enginePort",
]);

/**
 * Ne conserve d'une charge inconnue que les clés au type attendu (lecture
 * tolérante : le moteur peut n'exposer qu'une partie des réglages, ou davantage).
 */
function pickKnown(payload: unknown): Partial<Settings> {
  if (typeof payload !== "object" || payload === null) return {};
  const record = payload as Record<string, unknown>;
  const out: Partial<Settings> = {};
  for (const key of KEYS) {
    const incoming = record[key];
    if (incoming === undefined) continue;
    if (incoming === null) {
      if (NULLABLE_STRING.has(key) || NULLABLE_NUMBER.has(key)) {
        (out as Record<string, unknown>)[key] = null;
      }
      continue;
    }
    const expected = NULLABLE_STRING.has(key)
      ? "string"
      : NULLABLE_NUMBER.has(key)
        ? "number"
        : typeof DEFAULT_SETTINGS[key];
    if (typeof incoming === expected) {
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
