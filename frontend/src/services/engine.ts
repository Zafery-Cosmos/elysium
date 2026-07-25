/**
 * Client HTTP typé du moteur IA (contrat ARCHITECTURE.md §4, v0).
 *
 * Toutes les routes exigent `Authorization: Bearer <token>` ; l'endpoint est
 * découvert via Tauri IPC ou les variables d'env (voir endpoint.ts).
 */

import { getEngineEndpoint } from "./endpoint";
import { openSseStream, type RawSseEvent } from "./sse";
import type {
  ActionRequestEvent,
  Agent,
  AgentPermissions,
  AgentStatusEvent,
  Conversation,
  CustomProviderCreate,
  DecisionEvent,
  HealthInfo,
  ImportFolderResult,
  McpCatalogEntry,
  McpServer,
  McpServerInstall,
  Message,
  ModelsResponse,
  Project,
  ProjectCreate,
  ProviderConfig,
  ProviderInfo,
  ProviderTestResult,
  SendMessageOptions,
} from "../types/engine";

export const ENGINE_UNREACHABLE_MESSAGE =
  "Impossible de contacter le moteur IA — vérifiez qu'Elysium est bien démarré.";

export class EngineError extends Error {
  /** Message lisible, en français, destiné à l'utilisateur. */
  readonly humanMessage: string;
  readonly status: number | null;

  constructor(humanMessage: string, options?: { status?: number; cause?: unknown }) {
    super(humanMessage, { cause: options?.cause });
    this.name = "EngineError";
    this.humanMessage = humanMessage;
    this.status = options?.status ?? null;
  }
}

function httpHumanMessage(status: number, detail?: string): string {
  if (status === 401 || status === 403) {
    return "Accès au moteur IA refusé — le jeton de session est invalide. Relancez Elysium.";
  }
  if (status === 404) {
    return "Ressource introuvable côté moteur IA.";
  }
  if (status >= 500) {
    return "Le moteur IA a rencontré une erreur interne. Réessayez dans un instant.";
  }
  return detail ?? `Le moteur IA a refusé la requête (HTTP ${String(status)}).`;
}

async function request<T>(
  path: string,
  init?: { method?: string; body?: unknown },
): Promise<T> {
  let baseUrl: string;
  let token: string;
  try {
    ({ baseUrl, token } = await getEngineEndpoint());
  } catch (cause) {
    throw new EngineError(ENGINE_UNREACHABLE_MESSAGE, { cause });
  }

  let response: Response;
  try {
    response = await fetch(`${baseUrl}${path}`, {
      method: init?.method ?? "GET",
      headers: {
        Authorization: `Bearer ${token}`,
        ...(init?.body !== undefined
          ? { "Content-Type": "application/json" }
          : {}),
      },
      body: init?.body !== undefined ? JSON.stringify(init.body) : undefined,
    });
  } catch (cause) {
    throw new EngineError(ENGINE_UNREACHABLE_MESSAGE, { cause });
  }

  if (!response.ok) {
    let detail: string | undefined;
    try {
      const payload: unknown = await response.json();
      if (
        typeof payload === "object" &&
        payload !== null &&
        "detail" in payload &&
        typeof (payload as { detail: unknown }).detail === "string"
      ) {
        detail = (payload as { detail: string }).detail;
      }
    } catch {
      /* corps non JSON : on garde le message générique */
    }
    throw new EngineError(httpHumanMessage(response.status, detail), {
      status: response.status,
    });
  }

  if (response.status === 204) return undefined as T;
  try {
    return (await response.json()) as T;
  } catch (cause) {
    throw new EngineError("Réponse illisible du moteur IA.", { cause });
  }
}

/** Message d'erreur lisible pour n'importe quelle erreur attrapée. */
export function toHumanMessage(err: unknown): string {
  if (err instanceof EngineError) return err.humanMessage;
  return ENGINE_UNREACHABLE_MESSAGE;
}

/* ————— Normalisation d'enveloppes ({items: []} vs []) ————— */

function asList<T>(payload: unknown, key: string): T[] {
  if (Array.isArray(payload)) return payload as T[];
  if (typeof payload === "object" && payload !== null) {
    const record = payload as Record<string, unknown>;
    const nested = record[key] ?? record["items"];
    if (Array.isArray(nested)) return nested as T[];
  }
  return [];
}

/* ————— Routes ————— */

export const engine = {
  health: () => request<HealthInfo>("/health"),

  listProjects: async (): Promise<Project[]> =>
    asList<Project>(await request<unknown>("/projects"), "projects"),
  createProject: (data: ProjectCreate) =>
    request<Project>("/projects", { method: "POST", body: data }),
  getProject: (id: string) =>
    request<Project>(`/projects/${encodeURIComponent(id)}`),
  updateProject: (id: string, data: Partial<ProjectCreate>) =>
    request<Project>(`/projects/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: data,
    }),
  archiveProject: (id: string) =>
    request<void>(`/projects/${encodeURIComponent(id)}`, { method: "DELETE" }),
  importFolder: (id: string, path: string) =>
    request<ImportFolderResult>(
      `/projects/${encodeURIComponent(id)}/import-folder`,
      { method: "POST", body: { path } },
    ),

  listConversations: async (projectId: string): Promise<Conversation[]> =>
    asList<Conversation>(
      await request<unknown>(
        `/projects/${encodeURIComponent(projectId)}/conversations`,
      ),
      "conversations",
    ),
  createConversation: (projectId: string, title?: string) =>
    request<Conversation>(
      `/projects/${encodeURIComponent(projectId)}/conversations`,
      { method: "POST", body: title !== undefined ? { title } : {} },
    ),
  deleteConversation: (conversationId: string) =>
    request<void>(
      `/conversations/${encodeURIComponent(conversationId)}`,
      { method: "DELETE" },
    ),

  listMessages: async (conversationId: string): Promise<Message[]> =>
    asList<Message>(
      await request<unknown>(
        `/conversations/${encodeURIComponent(conversationId)}/messages`,
      ),
      "messages",
    ),
  sendMessage: (
    conversationId: string,
    content: string,
    options?: SendMessageOptions,
  ) =>
    request<{ id?: string }>(
      `/conversations/${encodeURIComponent(conversationId)}/messages`,
      {
        method: "POST",
        body: {
          content,
          ...(options?.mode !== undefined ? { mode: options.mode } : {}),
          ...(options?.execution !== undefined
            ? { execution: options.execution }
            : {}),
          ...(options?.model !== undefined ? { model: options.model } : {}),
          ...(options?.effort !== undefined ? { effort: options.effort } : {}),
        },
      },
    ),

  listModels: async (): Promise<ProviderInfo[]> =>
    asList<ProviderInfo>(
      await request<ModelsResponse | ProviderInfo[]>("/models"),
      "providers",
    ),
  configureProvider: (name: string, config: ProviderConfig) =>
    request<ProviderInfo | void>(
      `/models/providers/${encodeURIComponent(name)}`,
      { method: "PUT", body: config },
    ),
  addProvider: (data: CustomProviderCreate) =>
    request<ProviderInfo | void>("/models/providers", {
      method: "POST",
      body: data,
    }),
  testProvider: async (name: string): Promise<ProviderTestResult> => {
    const payload = await request<unknown>(
      `/models/providers/${encodeURIComponent(name)}/test`,
      { method: "POST" },
    );
    const record =
      typeof payload === "object" && payload !== null
        ? (payload as Record<string, unknown>)
        : {};
    const detail = record["detail"] ?? record["message"] ?? record["error"];
    return {
      reachable: record["reachable"] === true || record["ok"] === true,
      ...(typeof detail === "string" && detail.length > 0
        ? { detail }
        : {}),
    };
  },

  listAgents: async (): Promise<Agent[]> =>
    asList<Agent>(await request<unknown>("/agents"), "agents"),
  updateAgentPermissions: (role: string, permissions: AgentPermissions) =>
    request<Agent | void>(
      `/agents/${encodeURIComponent(role)}/permissions`,
      { method: "PATCH", body: permissions },
    ),

  getSettings: () => request<unknown>("/settings"),
  updateSettings: (patch: Record<string, unknown>) =>
    request<unknown>("/settings", { method: "PATCH", body: patch }),

  listMcpCatalog: async (): Promise<McpCatalogEntry[]> =>
    asList<McpCatalogEntry>(await request<unknown>("/mcp/catalog"), "catalog"),
  listMcpServers: async (): Promise<McpServer[]> =>
    asList<McpServer>(await request<unknown>("/mcp/servers"), "servers"),
  installMcpServer: (data: McpServerInstall) =>
    request<McpServer | void>("/mcp/servers", { method: "POST", body: data }),
  updateMcpServer: (id: string, data: { enabled?: boolean }) =>
    request<McpServer | void>(`/mcp/servers/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: data,
    }),
  removeMcpServer: (id: string) =>
    request<void>(`/mcp/servers/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
};

/* ————— Abonnement SSE ————— */

export interface StreamHandlers {
  onToken?: (text: string) => void;
  onAgentStatus?: (event: AgentStatusEvent) => void;
  onDecision?: (event: DecisionEvent) => void;
  onActionRequest?: (event: ActionRequestEvent) => void;
  onDone?: () => void;
  onError?: (humanMessage: string) => void;
}

function parseJson(data: string): Record<string, unknown> | null {
  try {
    const value: unknown = JSON.parse(data);
    return typeof value === "object" && value !== null
      ? (value as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

function str(record: Record<string, unknown> | null, ...keys: string[]): string | undefined {
  if (record === null) return undefined;
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string" && value.length > 0) return value;
  }
  return undefined;
}

function num(record: Record<string, unknown> | null, ...keys: string[]): number | undefined {
  if (record === null) return undefined;
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "number" && Number.isFinite(value)) return value;
  }
  return undefined;
}

function dispatchEvent(raw: RawSseEvent, handlers: StreamHandlers): void {
  const record = parseJson(raw.data);
  // Le type peut venir du champ SSE `event:` ou d'un champ JSON `type`.
  const type =
    raw.event !== "message" ? raw.event : (str(record, "type") ?? "token");

  switch (type) {
    case "token":
      handlers.onToken?.(
        str(record, "text", "content", "delta", "token") ??
          (record === null ? raw.data : ""),
      );
      break;
    case "agent_status":
      handlers.onAgentStatus?.({
        type: "agent_status",
        agent: str(record, "agent", "agent_name", "name") ?? "agent",
        status: str(record, "status", "state") ?? "thinking",
        task: str(record, "task", "current_task"),
        progress: num(record, "progress", "coverage", "confidence", "understanding"),
      });
      break;
    case "decision":
      handlers.onDecision?.({
        type: "decision",
        agent: str(record, "agent", "agent_name"),
        summary:
          str(record, "summary", "text", "content", "decision") ?? raw.data,
        progress: num(record, "progress", "coverage", "confidence", "understanding"),
      });
      break;
    case "action_request":
      handlers.onActionRequest?.({
        type: "action_request",
        agent: str(record, "agent", "agent_name"),
        action: str(record, "action", "tool", "capability"),
        summary:
          str(record, "summary", "description", "text", "content") ?? raw.data,
      });
      break;
    case "done":
      handlers.onDone?.();
      break;
    case "error":
      handlers.onError?.(
        str(record, "message", "detail", "error") ??
          "Le moteur IA a signalé une erreur pendant la génération.",
      );
      break;
    default:
      /* type inconnu : ignoré silencieusement (compat ascendante) */
      break;
  }
}

/**
 * S'abonne au flux SSE d'une conversation.
 * Retourne une fonction de désabonnement.
 */
export function streamConversation(
  conversationId: string,
  handlers: StreamHandlers,
): () => void {
  let closed = false;
  let close: () => void = () => {
    closed = true;
  };

  void getEngineEndpoint()
    .then(({ baseUrl, token }) => {
      if (closed) return;
      const connection = openSseStream({
        url: `${baseUrl}/conversations/${encodeURIComponent(conversationId)}/stream`,
        token,
        onEvent: (raw) => {
          dispatchEvent(raw, handlers);
        },
        onError: () => {
          handlers.onError?.(ENGINE_UNREACHABLE_MESSAGE);
        },
      });
      close = connection.close;
      if (closed) connection.close();
    })
    .catch(() => {
      handlers.onError?.(ENGINE_UNREACHABLE_MESSAGE);
    });

  return () => {
    closed = true;
    close();
  };
}
