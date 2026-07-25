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
  status?: AgentStatus;
  current_task?: string | null;
  permissions?: AgentPermissions;
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

export interface SendMessageOptions {
  mode?: ChatMode;
  /** "simple" = un seul modèle en solo, "expert" = l'équipe d'agents. */
  execution?: Execution;
  /** Format "provider:model_id". */
  model?: string;
  effort?: Effort;
}

/* ————— MCP (marketplace + serveurs installés) ————— */

export interface McpCatalogEntry {
  id: string;
  name?: string;
  description?: string;
  category?: string;
  transport?: string;
  command?: string | null;
  url?: string | null;
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
