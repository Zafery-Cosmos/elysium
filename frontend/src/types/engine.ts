/**
 * Types du contrat HTTP du moteur IA (ARCHITECTURE.md §4, v0).
 *
 * Le contrat v0 ne fige que les routes et les types d'événements SSE ;
 * les formes JSON exactes sont donc typées de façon tolérante (champs
 * optionnels, alias acceptés côté parsing dans services/engine.ts).
 */

export interface HealthInfo {
  status?: string;
  version?: string;
}

export type ProjectStatus =
  | "active"
  | "draft"
  | "paused"
  | "archived"
  | (string & {});

export interface Project {
  id: string;
  name: string;
  description?: string | null;
  status?: ProjectStatus;
  /** Heuristique de couverture 0–1 ou 0–100 selon le moteur. */
  progress?: number | null;
  created_at?: string;
  updated_at?: string;
}

export interface ProjectCreate {
  name: string;
  description?: string;
}

export interface Conversation {
  id: string;
  project_id?: string;
  title?: string | null;
  created_at?: string;
}

export type MessageRole = "user" | "assistant" | "system" | (string & {});

export interface Message {
  id: string;
  conversation_id?: string;
  role: MessageRole;
  content: string;
  /** Rôle de l'agent auteur (ex. "project_manager"), si assistant. */
  agent?: string | null;
  created_at?: string;
}

export type AgentStatus =
  | "thinking"
  | "analyzing"
  | "generating"
  | "waiting"
  | "done"
  | "error"
  | (string & {});

/** Accès au système de fichiers accordé à un rôle d'agent. */
export type FilesystemAccess = "none" | "read" | "read_write";

/** Profil de permissions d'un rôle (broker Rust, cf. ADR-003). */
export interface AgentPermissions {
  filesystem?: FilesystemAccess;
  shell?: boolean;
  network?: boolean;
}

export interface Agent {
  id?: string;
  name: string;
  role?: string;
  model?: string | null;
  permissions?: AgentPermissions;
  /** Faux = agent désactivé (grisé, exclu de l'équipe). Défaut : activé. */
  enabled?: boolean;
  /** Vrai pour les rôles intégrés (non supprimables ; désactivables). */
  builtin?: boolean;
  /** Prompt système de l'agent (surtout pour les agents personnalisés). */
  system_prompt?: string | null;
  description?: string | null;
}

/** POST /agents — création d'un agent personnalisé. */
export interface AgentCreate {
  name: string;
  role: string;
  system_prompt: string;
  model?: string | null;
  permissions?: AgentPermissions;
}

/** PATCH /agents/{role} — mise à jour tolérante (statut / permissions / modèle). */
export interface AgentPatch {
  enabled?: boolean;
  permissions?: AgentPermissions;
  model?: string | null;
  system_prompt?: string;
  name?: string;
}

/** Résumé renvoyé par POST /projects/{id}/import-folder (champs tolérants). */
export interface ImportFolderResult {
  path?: string;
  files?: number;
  directories?: number;
  total_size?: number;
  languages?: string[];
  summary?: string;
}

export interface ModelInfo {
  id?: string;
  name?: string;
  display_name?: string;
  /** Date de sortie ISO (souvent seule l'année est affichée). */
  release_date?: string;
  context_window?: number;
  /** Palier de coût 1–4, rendu « $ » à « $$$$ ». */
  cost_tier?: number;
  tier?: string;
  input_cost?: number;
  output_cost?: number;
  /** Modèle local détecté comme installé (Ollama, LM Studio…). */
  installed?: boolean;
}

export type ProviderName =
  | "anthropic"
  | "openai"
  | "ollama"
  | "lmstudio"
  | "openrouter"
  | "custom"
  | (string & {});

export interface ProviderInfo {
  name: ProviderName;
  label?: string;
  configured?: boolean;
  reachable?: boolean;
  base_url?: string | null;
  default_model?: string | null;
  /** "cloud" ou "local" selon le moteur ; heuristique côté UI sinon. */
  kind?: "cloud" | "local" | (string & {});
  models?: ModelInfo[];
}

export interface ModelsResponse {
  providers: ProviderInfo[];
}

export interface ProviderConfig {
  base_url?: string;
  api_key?: string;
}

/** POST /models/providers — fournisseur personnalisé compatible OpenAI. */
export interface CustomProviderCreate {
  name: string;
  base_url: string;
  api_key?: string;
  default_model?: string;
}

/** POST /models/providers/{name}/test */
export interface ProviderTestResult {
  reachable: boolean;
  detail?: string;
}

/* ————— Options d'envoi de message ————— */

export type ChatMode = "discuss" | "plan" | "edit";
export type Execution = "simple" | "expert";
export type Effort = "low" | "medium" | "high";

export type ExpertSubmode = "analyse" | "complet";

export type PreviewState =
  | "stopped"
  | "deps_missing"
  | "installing"
  | "starting"
  | "ready"
  | "compiling"
  | "compile_error"
  | "unreachable"
  | "stopping"
  | "failed";

/** GET /projects/{id}/preview — état réel du serveur de développement. */
export interface PreviewInfo {
  project_id: string;
  configured: boolean;
  state: PreviewState;
  root_path?: string;
  subdir?: string | null;
  app_root?: string | null;
  framework?: string | null;
  label?: string | null;
  package_manager?: string | null;
  script?: string | null;
  deps_installed?: boolean;
  hot_update?: "hmr" | "live-reload" | "full-reload";
  candidates?: string[];
  detection_error?: string | null;
  runnable?: boolean;
  needs_trust?: boolean;
  trusted?: boolean;
  port?: number | null;
  /** Renseignée seulement quand le serveur répond réellement. */
  url?: string | null;
  pid?: number | null;
  started_at?: string | null;
  error?: string | null;
  logs?: string[];
}

/* ————— Mémoire du projet ————— */

export type MemoryTier = "short" | "long";
export type MemoryKind = "note" | "fact" | "decision" | "constraint" | "preference" | "task_result";

export interface MemoryItem {
  id: string;
  project_id: string;
  tier: MemoryTier;
  kind: MemoryKind;
  title: string;
  content: string;
  /** user = saisi à la main · system = capturé automatiquement */
  source: "user" | "agent" | "system";
  pinned: boolean;
  /** Mémoire à court terme : date d'oubli (null = permanente). */
  expires_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface MemoryScanStats {
  files: number;
  /** Fichiers réellement relus cette fois. */
  read: number;
  /** Fichiers NON relus (inchangés) : c'est l'économie. */
  unchanged: number;
  removed: number;
  skipped: number;
  truncated: boolean;
  bytes_covered: number;
}

export interface MemoryOverview {
  project_id: string;
  folder: string | null;
  items: { short: number; long: number };
  files: {
    count: number;
    bytes: number;
    languages: Record<string, number>;
    last_scan_at: string | null;
    last_scan: MemoryScanStats | null;
  };
  context: { tokens: number; reread_tokens_avoided: number };
}

export interface MemoryGraphNode {
  id: string;
  language: string | null;
  size: number;
  summary: string;
  degree: number;
  dir: string;
}

export interface MemoryGraph {
  nodes: MemoryGraphNode[];
  edges: Array<{ source: string; target: string }>;
  total: number;
  truncated: boolean;
}

export interface MemoryFileRow {
  path: string;
  language: string | null;
  size: number;
  summary: string;
  imports: number;
  imported_by: number;
}

export interface MemoryFileLink {
  path: string;
  summary: string;
  language: string | null;
}

export interface MemoryFileDetail {
  path: string;
  language: string | null;
  size: number;
  summary: string;
  symbols: string[];
  external: string[];
  imports: MemoryFileLink[];
  imported_by: MemoryFileLink[];
  scanned_at: string;
}

export interface MemoryContext {
  text: string;
  tokens: number;
  budget_tokens: number;
  items: number;
  files: number;
}

/** POST /mcp/servers/{id}/test — démarre vraiment le serveur et liste ses outils. */
export interface McpTestResult {
  ok: boolean;
  tools: Array<{ name: string; description?: string }>;
  server_name?: string | null;
  server_version?: string | null;
  error?: string | null;
  duration_ms: number;
}

export interface SendMessageOptions {
  mode?: ChatMode;
  /** "simple" = un seul modèle en solo, "expert" = l'équipe d'agents. */
  execution?: Execution;
  /** Obligatoire côté moteur quand `execution === "expert"` (sinon erreur 422). */
  expertSubmode?: ExpertSubmode;
  /** Format "provider:model_id". */
  model?: string;
  effort?: Effort;
}

/* ————— MCP (marketplace + serveurs installés) ————— */

/** Un champ de configuration déclaré par un serveur MCP (config_schema). */
export interface McpConfigField {
  key: string;
  label?: string;
  /** "string" (texte), "secret" (mot de passe), "number". */
  type?: "string" | "secret" | "number" | (string & {});
  required?: boolean;
  description?: string;
  placeholder?: string;
  default?: string | number;
  /** Vrai si un secret est déjà enregistré (la valeur n'est jamais renvoyée). */
  secret_set?: boolean;
}

export interface McpCatalogEntry {
  id: string;
  name?: string;
  description?: string;
  category?: string;
  transport?: string;
  command?: string | null;
  url?: string | null;
  config_schema?: McpConfigField[];
}

/** POST /mcp/servers — depuis le catalogue ({catalog_id}) ou personnalisé. */
export interface McpServerInstall {
  catalog_id?: string;
  name?: string;
  transport?: string;
  command?: string;
  url?: string;
}

export interface McpServer {
  id: string;
  catalog_id?: string | null;
  name?: string;
  description?: string;
  category?: string;
  transport?: string;
  enabled?: boolean;
  command?: string | null;
  url?: string | null;
  config_schema?: McpConfigField[];
  /** Valeurs de configuration enregistrées (secrets masqués / absents). */
  config?: Record<string, string | number>;
}

/* ————— Événements SSE (/conversations/{id}/stream) ————— */

export type StreamEventType =
  | "token"
  | "agent_status"
  | "decision"
  | "action_request"
  | "done"
  | "error";

export interface TokenEvent {
  type: "token";
  text: string;
}

export interface AgentStatusEvent {
  type: "agent_status";
  agent: string;
  status: AgentStatus;
  task?: string;
  /** Couverture / compréhension éventuelle (0–1 ou 0–100). */
  progress?: number;
}

export interface DecisionEvent {
  type: "decision";
  agent?: string;
  summary: string;
  progress?: number;
  /** Nature de la décision (ex. "plan_tasks" : un plan vient d'être enregistré). */
  kind?: string;
  /** Nombre d'éléments concernés (ex. tâches du plan). */
  count?: number;
}

export interface ActionRequestEvent {
  type: "action_request";
  agent?: string;
  action?: string;
  summary: string;
}

export interface DoneEvent {
  type: "done";
}

export interface ErrorEvent {
  type: "error";
  message: string;
}

export type StreamEvent =
  | TokenEvent
  | AgentStatusEvent
  | DecisionEvent
  | ActionRequestEvent
  | DoneEvent
  | ErrorEvent;

/* ————— Administration (GET /admin/overview) ————— */

export interface AdminProviderStatus {
  name: string;
  kind: "anthropic" | "openai" | "cli" | (string & {});
  default_model: string;
  /** Connexion CLI (compte personnel) active ? null pour une clé API. */
  signed_in: boolean | null;
  detail: string | null;
  /** Le CLI (claude / codex) est-il installé sur cet ordinateur ? */
  installed?: boolean;
  /** Qui est connecté (CLI uniquement). */
  account?: { email?: string | null; plan?: string | null; expires_at?: string | null; method?: string | null } | null;
  /** api = facturé au token · subscription = abonnement CLI · local */
  billing: "api" | "subscription" | "local" | (string & {});
  /** État réel : un binaire installé ou une clé enregistrée ne prouve pas qu'on peut répondre. */
  health:
    | "not_installed"
    | "not_authenticated"
    | "authenticated"
    | "available"
    | "unavailable"
    | "auth_error"
    | "quota_exhausted"
    | "unknown";
  health_detail: string | null;
}

export interface AdminTotals {
  calls: number;
  errors: number;
  input_tokens: number;
  output_tokens: number;
  cache_tokens: number;
  /** USD rapporté par le fournisseur (CLI). */
  cost_reported_usd: number;
  /** USD estimé (tarif du catalogue × tokens). */
  cost_estimated_usd: number;
  /** rapporté + estimé */
  cost_usd: number;
  /** EUR converti avec le taux enregistré sur chaque appel. */
  cost_eur: number;
  /** Appels dont le coût est inconnu (inconnu ≠ zéro). */
  unknown_cost_calls: number;
  /** Moyenne sur les appels réussis uniquement. */
  avg_duration_ms: number;
}

export interface AdminFx {
  base: string;
  quote: string;
  rate: number;
  source: "user" | "ecb" | "default" | (string & {});
  as_of: string;
  /** true = valeur intégrée, pas un taux réel. */
  is_default: boolean;
}

export interface AdminGroup extends AdminTotals {
  key: string;
  last_used: string | null;
}

export interface AdminDay {
  day: string;
  provider: string;
  calls: number;
  input_tokens: number;
  output_tokens: number;
}

export type QuotaState = "unknown" | "stale" | "exhausted" | "ok";

export interface AdminQuotaWindow {
  name: string;
  /** 0–1 */
  utilization: number | null;
  /** Secondes epoch. */
  resets_at: number | null;
  state: QuotaState;
}

export interface AdminQuota {
  provider: string;
  kind: string;
  /** unknown = jamais reçu · stale = ancien ou fenêtre réinitialisée · exhausted · ok */
  state: QuotaState;
  /** Secondes epoch de la dernière lecture, null si jamais. */
  observed_at: number | null;
  windows: AdminQuotaWindow[];
}

export interface AdminError {
  at: string;
  provider: string;
  model: string;
  agent: string | null;
  message: string | null;
}

export interface AdminAction {
  at: string;
  agent: string | null;
  tool: string | null;
  status: string | null;
}

export interface AdminOverview {
  days: number;
  engine: { version: string; uptime_s: number };
  fx: AdminFx;
  by_billing: AdminGroup[];
  previews: {
    active: number;
    items: Array<{
      project_id: string;
      framework: string | null;
      state: PreviewState;
      port: number | null;
      url: string | null;
      started_at: string | null;
      error: string | null;
    }>;
  };
  providers: AdminProviderStatus[];
  totals: AdminTotals;
  by_provider: AdminGroup[];
  by_model: AdminGroup[];
  by_agent: AdminGroup[];
  by_day: AdminDay[];
  quotas: AdminQuota[];
  recent_errors: AdminError[];
  recent_actions: AdminAction[];
}
