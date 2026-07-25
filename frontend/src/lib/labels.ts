/** Libellés français et tons visuels des notions du moteur. */

import type {
  AgentPermissions,
  ChatMode,
  Effort,
  Execution,
} from "../types/engine";

export type Tone = "accent" | "ok" | "danger" | "info" | "muted";

export interface StatusMeta {
  label: string;
  tone: Tone;
  /** Statut « en cours » : le point du badge pulse. */
  live: boolean;
}

const AGENT_STATUS: Record<string, StatusMeta> = {
  thinking: { label: "Réflexion", tone: "accent", live: true },
  analyzing: { label: "Analyse", tone: "info", live: true },
  generating: { label: "Génération", tone: "accent", live: true },
  waiting: { label: "En attente", tone: "muted", live: false },
  done: { label: "Terminé", tone: "ok", live: false },
  error: { label: "Erreur", tone: "danger", live: false },
  idle: { label: "Au repos", tone: "muted", live: false },
};

export function agentStatusMeta(status: string | undefined): StatusMeta {
  if (status === undefined) return { label: "Inconnu", tone: "muted", live: false };
  return (
    AGENT_STATUS[status.toLowerCase()] ?? {
      label: status,
      tone: "muted",
      live: false,
    }
  );
}

const ROLES: Record<string, string> = {
  project_manager: "Chef de projet",
  pm: "Chef de projet",
  architect: "Architecte",
  frontend: "Développeur frontend",
  frontend_developer: "Développeur frontend",
  backend: "Développeur backend",
  backend_developer: "Développeur backend",
  database: "Ingénieur base de données",
  database_engineer: "Ingénieur base de données",
  devops: "DevOps",
  security: "Auditeur sécurité",
  security_auditor: "Auditeur sécurité",
  qa: "QA",
};

export function roleLabel(role: string | null | undefined): string | null {
  if (role === undefined || role === null || role.length === 0) return null;
  return ROLES[role.toLowerCase()] ?? role;
}

export interface ProviderMeta {
  name: string;
  label: string;
  description: string;
  needsApiKey: boolean;
  needsBaseUrl: boolean;
  /** Fournisseur exécuté sur la machine (Ollama, LM Studio…). */
  local: boolean;
  /** Conseil affiché quand le fournisseur local est injoignable. */
  localHint?: string;
}

/** Les fournisseurs affichés même si le moteur n'en renvoie aucun. */
export const KNOWN_PROVIDERS: ProviderMeta[] = [
  {
    name: "anthropic",
    label: "Anthropic",
    description: "Modèles Claude via l'API Anthropic.",
    needsApiKey: true,
    needsBaseUrl: false,
    local: false,
  },
  {
    name: "openai",
    label: "OpenAI",
    description: "Modèles GPT via l'API OpenAI.",
    needsApiKey: true,
    needsBaseUrl: false,
    local: false,
  },
  {
    name: "openrouter",
    label: "OpenRouter",
    description: "Passerelle multi-fournisseurs, une seule clé.",
    needsApiKey: true,
    needsBaseUrl: false,
    local: false,
  },
  {
    name: "ollama",
    label: "Ollama",
    description: "Modèles locaux, aucune clé requise.",
    needsApiKey: false,
    needsBaseUrl: true,
    local: true,
    localHint: "Lancez Ollama puis actualisez.",
  },
  {
    name: "lmstudio",
    label: "LM Studio",
    description: "Serveur local compatible OpenAI de LM Studio.",
    needsApiKey: false,
    needsBaseUrl: true,
    local: true,
    localHint: "Démarrez le serveur LM Studio puis actualisez.",
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
      description: "Fournisseur déclaré par le moteur.",
      needsApiKey: true,
      needsBaseUrl: true,
      local: false,
    }
  );
}

/* ————— Modes de conversation & effort ————— */

export const CHAT_MODES: Array<{
  value: ChatMode;
  label: string;
  hint: string;
}> = [
  {
    value: "discuss",
    label: "Discuter",
    hint: "Dialogue libre et questions adaptatives",
  },
  {
    value: "plan",
    label: "Plan",
    hint: "Produire un plan de projet structuré",
  },
  {
    value: "edit",
    label: "Éditer",
    hint: "Réviser la dernière réponse",
  },
];

export const CHAT_EXECUTIONS: Array<{
  value: Execution;
  label: string;
  hint: string;
}> = [
  {
    value: "simple",
    label: "Simple",
    hint: "Un seul modèle travaille en solo et vous propose d'en changer si besoin",
  },
  {
    value: "expert",
    label: "Expert",
    hint: "L'équipe d'agents collabore, se répartit le travail et débat des choix",
  },
];

export const EFFORT_LEVELS: Array<{ value: Effort; label: string }> = [
  { value: "low", label: "Faible" },
  { value: "medium", label: "Moyen" },
  { value: "high", label: "Élevé" },
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
