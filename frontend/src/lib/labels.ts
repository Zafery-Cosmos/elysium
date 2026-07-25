/** Métadonnées (tons, clés i18n, permissions) des notions du moteur. */

import type {
  AgentPermissions,
  ChatMode,
  Effort,
  Execution,
} from "../types/engine";
import type { MessageKey } from "../i18n/dictionaries";

export type Tone = "accent" | "ok" | "danger" | "info" | "muted";

export interface StatusMeta {
  /** Clé i18n du libellé (traduit par le composant via `t`). */
  labelKey: MessageKey;
  tone: Tone;
  /** Statut « en cours » : le point du badge pulse. */
  live: boolean;
}

const AGENT_STATUS: Record<string, StatusMeta> = {
  thinking: { labelKey: "status.thinking", tone: "accent", live: true },
  analyzing: { labelKey: "status.analyzing", tone: "info", live: true },
  generating: { labelKey: "status.generating", tone: "accent", live: true },
  waiting: { labelKey: "status.waiting", tone: "muted", live: false },
  done: { labelKey: "status.done", tone: "ok", live: false },
  error: { labelKey: "status.error", tone: "danger", live: false },
  idle: { labelKey: "status.idle", tone: "muted", live: false },
};

export function agentStatusMeta(status: string | undefined): StatusMeta {
  if (status === undefined) {
    return { labelKey: "status.unknown", tone: "muted", live: false };
  }
  return (
    AGENT_STATUS[status.toLowerCase()] ?? {
      labelKey: "status.unknown",
      tone: "muted",
      live: false,
    }
  );
}

const ROLE_KEYS: Record<string, MessageKey> = {
  project_manager: "role.project_manager",
  pm: "role.project_manager",
  architect: "role.architect",
  frontend: "role.frontend",
  frontend_developer: "role.frontend",
  backend: "role.backend",
  backend_developer: "role.backend",
  database: "role.database",
  database_engineer: "role.database",
  devops: "role.devops",
  security: "role.security",
  security_auditor: "role.security",
  qa: "role.qa",
};

/** Clé i18n du rôle, ou null si inconnu (le composant affiche alors le brut). */
export function roleLabelKey(role: string | null | undefined): MessageKey | null {
  if (role === undefined || role === null || role.length === 0) return null;
  return ROLE_KEYS[role.toLowerCase()] ?? null;
}

export interface ProviderMeta {
  name: string;
  label: string;
  /** Clé i18n de la description. */
  descKey: MessageKey;
  needsApiKey: boolean;
  needsBaseUrl: boolean;
  /** Fournisseur exécuté sur la machine (Ollama, LM Studio…). */
  local: boolean;
  /** Clé i18n du conseil affiché quand le fournisseur local est injoignable. */
  hintKey?: MessageKey;
}

/** Les fournisseurs affichés même si le moteur n'en renvoie aucun. */
export const KNOWN_PROVIDERS: ProviderMeta[] = [
  {
    name: "anthropic",
    label: "Anthropic",
    descKey: "provider.anthropic.desc",
    needsApiKey: true,
    needsBaseUrl: false,
    local: false,
  },
  {
    name: "openai",
    label: "OpenAI",
    descKey: "provider.openai.desc",
    needsApiKey: true,
    needsBaseUrl: false,
    local: false,
  },
  {
    name: "xai",
    label: "xAI",
    descKey: "provider.xai.desc",
    needsApiKey: true,
    needsBaseUrl: false,
    local: false,
  },
  {
    name: "openrouter",
    label: "OpenRouter",
    descKey: "provider.openrouter.desc",
    needsApiKey: true,
    needsBaseUrl: false,
    local: false,
  },
  {
    name: "ollama",
    label: "Ollama",
    descKey: "provider.ollama.desc",
    needsApiKey: false,
    needsBaseUrl: true,
    local: true,
    hintKey: "provider.ollama.hint",
  },
  {
    name: "lmstudio",
    label: "LM Studio",
    descKey: "provider.lmstudio.desc",
    needsApiKey: false,
    needsBaseUrl: true,
    local: true,
    hintKey: "provider.lmstudio.hint",
  },
];

const LOCAL_ALIASES = new Set(["ollama", "lmstudio", "lm_studio", "lm-studio"]);

/** Normalise les alias « lm_studio » / « lm-studio » vers « lmstudio ». */
export function canonicalProviderName(name: string): string {
  const lower = name.toLowerCase();
  return LOCAL_ALIASES.has(lower) && lower !== "ollama" ? "lmstudio" : lower;
}

export function isLocalProviderName(name: string): boolean {
  return LOCAL_ALIASES.has(name.toLowerCase());
}

export function providerMeta(name: string): ProviderMeta {
  const canonical = canonicalProviderName(name);
  return (
    KNOWN_PROVIDERS.find((p) => p.name === canonical) ?? {
      name,
      label: name,
      descKey: "provider.generic.desc",
      needsApiKey: true,
      needsBaseUrl: true,
      local: false,
    }
  );
}

/* ————— Modes de conversation & effort (clés i18n, traduites au rendu) ————— */

export const CHAT_MODES: Array<{
  value: ChatMode;
  labelKey: MessageKey;
  hintKey: MessageKey;
}> = [
  { value: "discuss", labelKey: "chat.mode.discuss", hintKey: "chat.mode.discuss.hint" },
  { value: "plan", labelKey: "chat.mode.plan", hintKey: "chat.mode.plan.hint" },
  { value: "edit", labelKey: "chat.mode.edit", hintKey: "chat.mode.edit.hint" },
];

export const CHAT_EXECUTIONS: Array<{
  value: Execution;
  labelKey: MessageKey;
  hintKey: MessageKey;
}> = [
  { value: "simple", labelKey: "chat.exec.simple", hintKey: "chat.exec.simple.hint" },
  { value: "expert", labelKey: "chat.exec.expert", hintKey: "chat.exec.expert.hint" },
];

export const EFFORT_LEVELS: Array<{ value: Effort; labelKey: MessageKey }> = [
  { value: "low", labelKey: "chat.effort.low" },
  { value: "medium", labelKey: "chat.effort.medium" },
  { value: "high", labelKey: "chat.effort.high" },
];

/* ————— Rôles d'agents & permissions par défaut (deny-by-default) ————— */

export interface AgentRoleMeta {
  role: string;
  permissions: AgentPermissions;
}

/** Les 8 rôles de l'équipe et leurs permissions par défaut raisonnables. */
export const DEFAULT_AGENT_ROLES: AgentRoleMeta[] = [
  { role: "project_manager", permissions: { filesystem: "read", shell: false, network: false } },
  { role: "architect", permissions: { filesystem: "read", shell: false, network: false } },
  { role: "frontend", permissions: { filesystem: "read_write", shell: false, network: false } },
  { role: "backend", permissions: { filesystem: "read_write", shell: true, network: true } },
  { role: "database", permissions: { filesystem: "read_write", shell: false, network: false } },
  { role: "devops", permissions: { filesystem: "read_write", shell: true, network: true } },
  { role: "security", permissions: { filesystem: "read", shell: false, network: true } },
  { role: "qa", permissions: { filesystem: "read", shell: true, network: false } },
];
