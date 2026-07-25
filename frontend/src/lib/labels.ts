/** Libellés français et tons visuels des notions du moteur. */

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
}

/** Les cinq fournisseurs affichés même si le moteur n'en renvoie aucun. */
export const KNOWN_PROVIDERS: ProviderMeta[] = [
  {
    name: "anthropic",
    label: "Anthropic",
    description: "Modèles Claude via l'API Anthropic.",
    needsApiKey: true,
    needsBaseUrl: false,
  },
  {
    name: "openai",
    label: "OpenAI",
    description: "Modèles GPT via l'API OpenAI.",
    needsApiKey: true,
    needsBaseUrl: false,
  },
  {
    name: "ollama",
    label: "Ollama",
    description: "Modèles locaux, aucune clé requise.",
    needsApiKey: false,
    needsBaseUrl: true,
  },
  {
    name: "openrouter",
    label: "OpenRouter",
    description: "Passerelle multi-fournisseurs.",
    needsApiKey: true,
    needsBaseUrl: false,
  },
  {
    name: "custom",
    label: "Serveur personnalisé",
    description: "Tout serveur compatible OpenAI (LM Studio, vLLM…).",
    needsApiKey: false,
    needsBaseUrl: true,
  },
];

export function providerMeta(name: string): ProviderMeta {
  return (
    KNOWN_PROVIDERS.find((p) => p.name === name.toLowerCase()) ?? {
      name,
      label: name,
      description: "Fournisseur déclaré par le moteur.",
      needsApiKey: true,
      needsBaseUrl: true,
    }
  );
}
