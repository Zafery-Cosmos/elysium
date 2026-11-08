import { create } from "zustand";
import { persist } from "zustand/middleware";
import { engine, toHumanMessage } from "../services/engine";
import type { Effort } from "../types/engine";

/**
 * Réglages de l'application. RÈGLE : chaque réglage ici a un effet réel —
 * soit local (apparence, confirmations, reprise), soit côté moteur (envoyé
 * via `PATCH /settings`, lu par le moteur à chaque message). Un réglage dont
 * la fonctionnalité n'existe pas encore n'a PAS sa place ici : on l'ajoute
 * avec la fonctionnalité (mémoire, débats d'agents, chiffrement, etc.).
 */

export type Language = "fr" | "en" | "es";
export type Theme = "light" | "dark" | "auto";
export type Density = "comfortable" | "compact";
export type Motion = "auto" | "on" | "reduced";
export type FontSize = "small" | "normal" | "large";
export type AiLanguage = "auto" | "fr" | "en" | "es";
export type LogLevel = "error" | "warn" | "info" | "debug";
export type CacheTtl = "5m" | "1h";

export interface Settings {
  // ————— Général (local) —————
  language: Language;
  theme: Theme;
  density: Density;
  motion: Motion;
  fontSize: FontSize;
  /** Rouvre la dernière conversation au lancement. */
  resumeLastConversation: boolean;
  /** Demande confirmation avant toute suppression. */
  confirmBeforeDelete: boolean;
  /** Langue imposée aux réponses de l'IA (moteur). */
  aiResponseLanguage: AiLanguage;

  // ————— Intelligence artificielle (moteur) —————
  /** "fournisseur:modèle" imposé, null = choix automatique du moteur. */
  defaultModel: string | null;
  defaultEffort: Effort;
  autoRouting: boolean;
  streaming: boolean;
  /** Plafond de tokens par réponse (API ; ignoré par les CLI Claude Code / Codex). */
  maxResponseTokens: number;
  /** Délai d'expiration d'une requête, en secondes. */
  requestTimeout: number;
  maxRetries: number;

  // ————— Cache de prompt (moteur, API Anthropic uniquement) —————
  cacheEnabled: boolean;
  cacheTtl: CacheTtl;
  cacheMinPrefix: number;

  // ————— Développeur (moteur) —————
  logLevel: LogLevel;

  // ————— Confidentialité (moteur) —————
  /** Masque clés/mots de passe dans les messages avant envoi à une IA. */
  redactSecrets: boolean;
  /** N'utilise que des modèles tournant sur cet ordinateur. */
  localOnly: boolean;
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

  defaultModel: null,
  defaultEffort: "medium",
  autoRouting: true,
  streaming: true,
  maxResponseTokens: 8192,
  requestTimeout: 120,
  maxRetries: 2,

  cacheEnabled: true,
  cacheTtl: "5m",
  cacheMinPrefix: 1024,

  logLevel: "warn",

  redactSecrets: true,
  localOnly: false,
};

interface SettingsState extends Settings {
  /** Horodatage du dernier enregistrement (pour l'indicateur « Enregistré »). */
  savedAt: number | null;
  /** Message si le moteur a refusé / n'a pas reçu le dernier changement. */
  syncError: string | null;
  set: <K extends keyof Settings>(key: K, value: Settings[K]) => void;
  syncFromEngine: () => Promise<void>;
}

/* ————— Application des effets sur le document ————— */

const FONT_PX: Record<FontSize, number> = {
  small: 14.5,
  normal: 16,
  large: 17.5,
};

function prefersDark(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-color-scheme: dark)").matches
  );
}

/** Thème effectif (clair/sombre) : « auto » suit la préférence système. */
function isDark(theme: Theme): boolean {
  if (theme === "dark") return true;
  if (theme === "light") return false;
  return prefersDark();
}

function applyToDocument(s: Settings): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;

  // Les lecteurs d'écran prononcent la page selon cet attribut.
  root.lang = s.language;

  // Densité : posée en attribut ; le CSS resserre l'interlignage en compact.
  root.dataset.density = s.density;

  // Taille de police racine (rem) : combine taille choisie et densité
  // (le mode compact resserre d'un point).
  const px = FONT_PX[s.fontSize] - (s.density === "compact" ? 1 : 0);
  root.style.fontSize = `${String(px)}px`;

  // Thème : bascule la classe `dark` (palette inversée) + color-scheme, en
  // direct. « auto » suit prefers-color-scheme (écouté ci-dessous).
  root.dataset.theme = s.theme;
  const dark = isDark(s.theme);
  root.classList.toggle("dark", dark);
  root.style.colorScheme = dark ? "dark" : "light";

  // Animations : classe qui prime sur / renforce prefers-reduced-motion.
  root.classList.remove("motion-force", "motion-reduce");
  if (s.motion === "on") root.classList.add("motion-force");
  else if (s.motion === "reduced") root.classList.add("motion-reduce");
}

/** Réapplique le thème quand le système bascule clair/sombre (mode « auto »). */
let themeMediaBound = false;
function bindThemeMedia(): void {
  if (themeMediaBound || typeof window === "undefined") return;
  if (typeof window.matchMedia !== "function") return;
  themeMediaBound = true;
  const mq = window.matchMedia("(prefers-color-scheme: dark)");
  mq.addEventListener("change", () => {
    if (useSettingsStore.getState().theme === "auto") {
      applyToDocument(useSettingsStore.getState());
    }
  });
}

/* ————— Correspondance avec le document du moteur —————
 *
 * Le moteur stocke un document IMBRIQUÉ (`{ai: {streaming: …}}`, schéma
 * `extra: forbid`). Seuls les réglages que le moteur lit réellement y sont
 * envoyés ; les réglages purement locaux (thème, confirmations…) restent ici.
 */

type Json = Record<string, unknown>;

function asRecord(value: unknown): Json {
  return typeof value === "object" && value !== null ? (value as Json) : {};
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, Math.round(value)));
}

/** Convertit des changements locaux en fragment de document moteur. */
export function toEnginePatch(patch: Partial<Settings>): Json {
  const out: Record<string, Json> = {};
  const put = (section: string, key: string, value: unknown): void => {
    (out[section] ??= {})[key] = value;
  };
  for (const [key, value] of Object.entries(patch) as Array<[keyof Settings, never]>) {
    switch (key) {
      case "aiResponseLanguage":
        put("general", "ai_response_language", value);
        break;
      case "defaultModel": {
        const ref = value as string | null;
        const cut = ref === null ? -1 : ref.indexOf(":");
        put("ai", "default_provider", cut > 0 && ref !== null ? ref.slice(0, cut) : null);
        put("ai", "default_model", cut > 0 && ref !== null ? ref.slice(cut + 1) : null);
        break;
      }
      case "defaultEffort":
        put("ai", "default_effort", value);
        break;
      case "autoRouting":
        put("ai", "auto_routing", value);
        break;
      case "streaming":
        put("ai", "streaming", value);
        break;
      case "maxResponseTokens":
        put("ai", "max_response_tokens", clamp(Number(value), 1, 200_000));
        break;
      case "requestTimeout":
        put("ai", "request_timeout_s", clamp(Number(value), 1, 3600));
        break;
      case "maxRetries":
        put("ai", "max_retries", clamp(Number(value), 0, 10));
        break;
      case "cacheEnabled":
        put("prompt_caching", "enabled", value);
        break;
      case "cacheTtl":
        put("prompt_caching", "ttl", value);
        break;
      case "cacheMinPrefix":
        put("prompt_caching", "min_prefix_tokens", Math.max(0, Math.round(Number(value))));
        break;
      case "logLevel":
        put("developer", "log_level", value === "warn" ? "warning" : value);
        break;
      case "redactSecrets":
        put("privacy", "redact_secrets_before_send", value);
        break;
      case "localOnly":
        put("privacy", "local_only", value);
        break;
      default:
        break; // réglage local : rien à envoyer
    }
  }
  return out;
}

/** Lit le document du moteur (tolérant) et renvoie les réglages locaux correspondants. */
export function fromEngineDocument(payload: unknown): Partial<Settings> {
  const doc = asRecord(payload);
  const general = asRecord(doc["general"]);
  const ai = asRecord(doc["ai"]);
  const cache = asRecord(doc["prompt_caching"]);
  const dev = asRecord(doc["developer"]);
  const privacy = asRecord(doc["privacy"]);
  const out: Partial<Settings> = {};

  const oneOf = <T extends string>(v: unknown, allowed: readonly T[]): T | undefined =>
    typeof v === "string" && (allowed as readonly string[]).includes(v) ? (v as T) : undefined;
  const bool = (v: unknown): boolean | undefined => (typeof v === "boolean" ? v : undefined);
  const num = (v: unknown): number | undefined =>
    typeof v === "number" && Number.isFinite(v) ? v : undefined;
  const assign = <K extends keyof Settings>(key: K, value: Settings[K] | undefined): void => {
    if (value !== undefined) out[key] = value;
  };

  assign("aiResponseLanguage", oneOf(general["ai_response_language"], ["auto", "fr", "en", "es"] as const));
  if (typeof ai["default_provider"] === "string" && typeof ai["default_model"] === "string") {
    out.defaultModel = `${ai["default_provider"]}:${ai["default_model"]}`;
  } else if ("default_provider" in ai) {
    out.defaultModel = null;
  }
  assign("defaultEffort", oneOf(ai["default_effort"], ["low", "medium", "high"] as const));
  assign("autoRouting", bool(ai["auto_routing"]));
  assign("streaming", bool(ai["streaming"]));
  assign("maxResponseTokens", num(ai["max_response_tokens"]));
  assign("requestTimeout", num(ai["request_timeout_s"]));
  assign("maxRetries", num(ai["max_retries"]));
  assign("cacheEnabled", bool(cache["enabled"]));
  assign("cacheTtl", oneOf(cache["ttl"], ["5m", "1h"] as const));
  assign("cacheMinPrefix", num(cache["min_prefix_tokens"]));
  const level = dev["log_level"] === "warning" ? "warn" : dev["log_level"];
  assign("logLevel", oneOf(level, ["error", "warn", "info", "debug"] as const));
  assign("redactSecrets", bool(privacy["redact_secrets_before_send"]));
  assign("localOnly", bool(privacy["local_only"]));
  return out;
}

function deepMerge(a: Json, b: Json): Json {
  const out: Json = { ...a };
  for (const [key, value] of Object.entries(b)) {
    const existing = out[key];
    out[key] =
      typeof existing === "object" &&
      existing !== null &&
      typeof value === "object" &&
      value !== null
        ? deepMerge(existing as Json, value as Json)
        : value;
  }
  return out;
}

let patchTimer: ReturnType<typeof setTimeout> | null = null;
let pendingPatch: Json = {};

/** Envoi différé vers PATCH /settings ; un échec est signalé à l'utilisateur. */
function schedulePatch(patch: Partial<Settings>): void {
  const fragment = toEnginePatch(patch);
  if (Object.keys(fragment).length === 0) return; // réglage local
  pendingPatch = deepMerge(pendingPatch, fragment);
  if (patchTimer !== null) clearTimeout(patchTimer);
  patchTimer = setTimeout(() => {
    const body = pendingPatch;
    pendingPatch = {};
    patchTimer = null;
    engine
      .updateSettings(body)
      .then(() => {
        useSettingsStore.setState({ syncError: null });
      })
      .catch((err: unknown) => {
        useSettingsStore.setState({ syncError: toHumanMessage(err) });
      });
  }, 400);
}

/** Valeurs persistées par une ancienne version : on ne garde que du valide. */
function migrate(persisted: unknown): Partial<Settings> {
  const old = asRecord(persisted);
  const out: Partial<Settings> = {};
  for (const key of Object.keys(DEFAULT_SETTINGS) as Array<keyof Settings>) {
    const incoming = old[key];
    const fallback = DEFAULT_SETTINGS[key];
    if (incoming === null && fallback === null) (out as Json)[key] = null;
    else if (incoming !== undefined && incoming !== null && typeof incoming === typeof fallback)
      (out as Json)[key] = incoming;
    else if (key === "defaultModel" && typeof incoming === "string") out.defaultModel = incoming;
  }
  if (out.cacheTtl !== undefined && out.cacheTtl !== "5m" && out.cacheTtl !== "1h") {
    out.cacheTtl = "5m"; // l'ancien palier « 24h » n'existe pas côté moteur
  }
  return out;
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set, get) => ({
      ...DEFAULT_SETTINGS,
      savedAt: null,
      syncError: null,

      set: (key, value) => {
        set({ [key]: value, savedAt: Date.now() } as Partial<SettingsState>);
        applyToDocument(get());
        schedulePatch({ [key]: value } as Partial<Settings>);
      },

      syncFromEngine: async () => {
        let remote: unknown;
        try {
          remote = await engine.getSettings();
        } catch {
          return; // moteur injoignable : on garde les valeurs locales
        }
        const known = fromEngineDocument(remote);
        if (Object.keys(known).length === 0) return;
        set(known as Partial<SettingsState>);
        applyToDocument(get());
      },
    }),
    {
      name: "elysium-settings",
      version: 2,
      // Seuls les réglages sont mémorisés (pas `savedAt` / `syncError`).
      partialize: (s) =>
        Object.fromEntries(
          (Object.keys(DEFAULT_SETTINGS) as Array<keyof Settings>).map((k) => [k, s[k]]),
        ) as unknown as SettingsState,
      migrate: (persisted) => migrate(persisted) as SettingsState,
      onRehydrateStorage: () => (state) => {
        if (state) applyToDocument(state);
      },
    },
  ),
);

/** Applique les effets au démarrage (avant tout rendu dépendant du DOM). */
export function bootstrapSettings(): void {
  applyToDocument(useSettingsStore.getState());
  bindThemeMedia();
}
