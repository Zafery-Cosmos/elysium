import { create } from "zustand";
import { engine, streamConversation, toHumanMessage } from "../services/engine";
import type { ChatMode, Execution, Effort, Message } from "../types/engine";
import type { LoadStatus } from "./projects";

/** Entrée lisible du fil « Activité de l'équipe ». */
export interface TeamEvent {
  id: number;
  at: number;
  kind: "agent_status" | "decision" | "action_request";
  agent: string | null;
  status: string | null;
  summary: string;
}

/** Préférences d'envoi retenues par conversation (mode, modèle, effort). */
export interface ChatPrefs {
  mode: ChatMode;
  execution: Execution;
  /** Format "provider:model_id", null = routage automatique du moteur. */
  model: string | null;
  effort: Effort;
}

const DEFAULT_PREFS: ChatPrefs = { mode: "discuss", execution: "simple", model: null, effort: "medium" };

interface ChatState {
  projectId: string | null;
  conversationId: string | null;
  messages: Message[];
  messagesStatus: LoadStatus;
  error: string | null;
  /** Erreur non fatale survenue pendant le flux (bandeau discret). */
  streamError: string | null;
  streamBuffer: string;
  streaming: boolean;
  sending: boolean;
  events: TeamEvent[];
  /** Compréhension du projet, 0–1 (heuristique de couverture, cf. ADR-005). */
  understanding: number;
  /** Mode / exécution / modèle / effort de la conversation ouverte. */
  mode: ChatMode;
  execution: Execution;
  model: string | null;
  effort: Effort;
  openForProject: (projectId: string) => Promise<void>;
  send: (content: string) => Promise<void>;
  setMode: (mode: ChatMode) => void;
  setExecution: (execution: Execution) => void;
  setModel: (model: string | null) => void;
  setEffort: (effort: Effort) => void;
  close: () => void;
}

let unsubscribe: (() => void) | null = null;
let eventSeq = 0;
let localSeq = 0;

/** Préférences conservées par projet, le temps de la session. */
const prefsByProject = new Map<string, ChatPrefs>();

function rememberPrefs(projectId: string | null, prefs: Partial<ChatPrefs>): void {
  if (projectId === null) return;
  const current = prefsByProject.get(projectId) ?? { ...DEFAULT_PREFS };
  prefsByProject.set(projectId, { ...current, ...prefs });
}

/** Normalise une progression exprimée en 0–1 ou 0–100. */
function normalizeProgress(value: number): number {
  const scaled = value > 1 ? value / 100 : value;
  return Math.min(1, Math.max(0, scaled));
}

export const useChatStore = create<ChatState>((set, get) => {
  const pushEvent = (event: Omit<TeamEvent, "id" | "at">): void => {
    eventSeq += 1;
    set((state) => ({
      events: [...state.events.slice(-199), { ...event, id: eventSeq, at: Date.now() }],
    }));
  };

  const bumpUnderstanding = (explicit: number | undefined, fallback: number): void => {
    set((state) => ({
      understanding:
        explicit !== undefined
          ? Math.max(state.understanding, normalizeProgress(explicit))
          : Math.min(0.98, state.understanding + fallback),
    }));
  };

  const flushBuffer = (): void => {
    const { streamBuffer, events } = get();
    if (streamBuffer.length === 0) {
      set({ streaming: false });
      return;
    }
    const lastAgent = [...events]
      .reverse()
      .find((e) => e.kind === "agent_status" && e.status === "generating");
    localSeq += 1;
    const message: Message = {
      id: `local-${String(localSeq)}`,
      role: "assistant",
      content: streamBuffer,
      agent: lastAgent?.agent ?? null,
    };
    set((state) => ({
      messages: [...state.messages, message],
      streamBuffer: "",
      streaming: false,
    }));
  };

  const startStream = (conversationId: string): void => {
    unsubscribe?.();
    unsubscribe = streamConversation(conversationId, {
      onToken: (text) => {
        if (text.length === 0) return;
        set((state) => ({
          streamBuffer: state.streamBuffer + text,
          streaming: true,
        }));
      },
      onAgentStatus: (event) => {
        pushEvent({
          kind: "agent_status",
          agent: event.agent,
          status: event.status,
          summary: event.task ?? "",
        });
        bumpUnderstanding(event.progress, 0.01);
      },
      onDecision: (event) => {
        pushEvent({
          kind: "decision",
          agent: event.agent ?? null,
          status: null,
          summary: event.summary,
        });
        bumpUnderstanding(event.progress, 0.06);
      },
      onActionRequest: (event) => {
        pushEvent({
          kind: "action_request",
          agent: event.agent ?? null,
          status: null,
          summary: event.summary,
        });
      },
      onDone: () => {
        flushBuffer();
        set({ sending: false });
      },
      onError: (humanMessage) => {
        flushBuffer();
        set({ streamError: humanMessage, sending: false });
      },
    });
  };

  return {
    projectId: null,
    conversationId: null,
    messages: [],
    messagesStatus: "idle",
    error: null,
    streamError: null,
    streamBuffer: "",
    streaming: false,
    sending: false,
    events: [],
    understanding: 0,
    mode: DEFAULT_PREFS.mode,
    execution: DEFAULT_PREFS.execution,
    model: DEFAULT_PREFS.model,
    effort: DEFAULT_PREFS.effort,

    openForProject: async (projectId) => {
      unsubscribe?.();
      unsubscribe = null;
      // Préférences propres au projet si connues ; sinon on conserve celles en
      // mémoire (ex. choix fait sur l'accueil avant la création du projet).
      const state = get();
      const prefs: ChatPrefs =
        prefsByProject.get(projectId) ?? {
          mode: state.mode,
          execution: state.execution,
          model: state.model,
          effort: state.effort,
        };
      set({
        projectId,
        conversationId: null,
        messages: [],
        messagesStatus: "loading",
        error: null,
        streamError: null,
        streamBuffer: "",
        streaming: false,
        sending: false,
        events: [],
        understanding: 0,
        mode: prefs.mode,
        execution: prefs.execution,
        model: prefs.model,
        effort: prefs.effort,
      });
      try {
        const conversations = await engine.listConversations(projectId);
        if (get().projectId !== projectId) return; // navigation entre-temps
        const first = conversations[0];
        if (first === undefined) {
          // Aucune conversation : elle sera créée au premier message.
          set({ messagesStatus: "ready" });
          return;
        }
        set({ conversationId: first.id });
        const messages = await engine.listMessages(first.id);
        if (get().projectId !== projectId) return;
        set({ messages, messagesStatus: "ready" });
        startStream(first.id);
      } catch (err) {
        if (get().projectId !== projectId) return;
        set({ messagesStatus: "error", error: toHumanMessage(err) });
      }
    },

    send: async (content) => {
      const trimmed = content.trim();
      const { projectId, sending } = get();
      if (trimmed.length === 0 || projectId === null || sending) return;
      set({ sending: true, streamError: null });
      try {
        let conversationId = get().conversationId;
        if (conversationId === null) {
          const conversation = await engine.createConversation(projectId);
          conversationId = conversation.id;
          set({ conversationId });
          startStream(conversationId);
        }
        localSeq += 1;
        const userMessage: Message = {
          id: `local-${String(localSeq)}`,
          role: "user",
          content: trimmed,
        };
        set((state) => ({ messages: [...state.messages, userMessage] }));
        const { mode, execution, model, effort } = get();
        await engine.sendMessage(conversationId, trimmed, {
          mode,
          execution,
          ...(model !== null ? { model } : {}),
          effort,
        });
        // `sending` repasse à false sur l'événement done/error du flux.
      } catch (err) {
        set({ sending: false, streamError: toHumanMessage(err) });
      }
    },

    setMode: (mode) => {
      rememberPrefs(get().projectId, { mode });
      set({ mode });
    },
    setExecution: (execution) => {
      rememberPrefs(get().projectId, { execution });
      set({ execution });
    },

    setModel: (model) => {
      rememberPrefs(get().projectId, { model });
      set({ model });
    },

    setEffort: (effort) => {
      rememberPrefs(get().projectId, { effort });
      set({ effort });
    },

    close: () => {
      unsubscribe?.();
      unsubscribe = null;
      set({ streaming: false, sending: false });
    },
  };
});
