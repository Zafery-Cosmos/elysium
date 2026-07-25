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

export interface Agent {
  id?: string;
  name: string;
  role?: string;
  model?: string | null;
  status?: AgentStatus;
  current_task?: string | null;
}

export interface ModelInfo {
  id?: string;
  name?: string;
  context_window?: number;
}

export type ProviderName =
  | "anthropic"
  | "openai"
  | "ollama"
  | "openrouter"
  | "custom"
  | (string & {});

export interface ProviderInfo {
  name: ProviderName;
  label?: string;
  configured?: boolean;
  reachable?: boolean;
  base_url?: string | null;
  models?: ModelInfo[];
}

export interface ModelsResponse {
  providers: ProviderInfo[];
}

export interface ProviderConfig {
  base_url?: string;
  api_key?: string;
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
