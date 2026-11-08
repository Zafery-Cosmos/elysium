import { create } from "zustand";
import { engine, streamConversation, toHumanMessage } from "../services/engine";
import type {
  ChatMode,
  Execution,
  Effort,
  ExpertSubmode,
  Message,
  PendingAction,
} from "../types/engine";
import type { LoadStatus } from "./projects";
import { translate, type MessageKey } from "../i18n";
import { useSettingsStore } from "./settings";
import { useUiStore } from "./ui";

/** Texte localisé (langue des réglages) pour les messages générés par le store. */
function planText(key: MessageKey, params?: Record<string, string | number>): string {
  return translate(useSettingsStore.getState().language, key, params);
}

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
  expertSubmode: ExpertSubmode;
  /** Format "provider:model_id", null = routage automatique du moteur. */
  model: string | null;
  effort: Effort;
}

/** Préférences d'une conversation neuve ; l'effort suit le réglage « Effort par défaut ». */
function defaultPrefs(): ChatPrefs {
  return {
    mode: "discuss",
    execution: "simple",
    expertSubmode: "analyse",
    model: null,
    effort: useSettingsStore.getState().defaultEffort,
  };
}

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
  expertSubmode: ExpertSubmode;
  model: string | null;
  effort: Effort;
  /** Outils MCP demandés par un agent, en attente de décision. */
  pendingActions: PendingAction[];
  /** Augmente quand l'équipe propose des fichiers (la revue se recharge). */
  changesVersion: number;
  /** Le mode Complet attend qu'un dossier soit relié au projet. */
  workspaceRequired: boolean;
  /** Plan fraîchement généré, en attente de validation (null = rien à valider). */
  pendingPlan: { count: number } | null;
  /** Message qui n'a pas pu partir : rendu à la saisie pour ne pas le perdre. */
  failedDraft: string | null;
  consumeFailedDraft: () => void;
  openForProject: (projectId: string) => Promise<void>;
  /** `overrides` : valeurs d'envoi ponctuelles qui ne modifient pas les préférences. */
  send: (
    content: string,
    overrides?: { mode?: ChatMode; execution?: Execution; expertSubmode?: ExpertSubmode },
  ) => Promise<void>;
  /** Valide le plan : l'équipe l'analyse, ou propose les fichiers (Complet). */
  approvePlan: (submode?: ExpertSubmode) => Promise<void>;
  /** Arrête le travail en cours. */
  cancel: () => Promise<void>;
  decideAction: (actionId: string, approved: boolean) => Promise<void>;
  dismissWorkspaceRequest: () => void;
  /** Refuse le plan : retire ses tâches non commencées. */
  rejectPlan: () => Promise<void>;
  setMode: (mode: ChatMode) => void;
  setExecution: (execution: Execution, expertSubmode?: ExpertSubmode) => void;
  setModel: (model: string | null) => void;
  setEffort: (effort: Effort) => void;
  close: () => void;
}

let unsubscribe: (() => void) | null = null;
/** Change à chaque ouverture/fermeture : invalide tout ce qui était en vol. */
let openSeq = 0;
let rejectingPlan = false;
let eventSeq = 0;
let localSeq = 0;

/** Préférences conservées par projet, le temps de la session. */
const prefsByProject = new Map<string, ChatPrefs>();

function rememberPrefs(projectId: string | null, prefs: Partial<ChatPrefs>): void {
  if (projectId === null) return;
  const current = prefsByProject.get(projectId) ?? defaultPrefs();
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

  /** Seule une couverture réellement mesurée fait avancer la jauge. */
  const bumpUnderstanding = (explicit: number | undefined): void => {
    if (explicit === undefined) return;
    set((state) => ({ understanding: Math.max(state.understanding, normalizeProgress(explicit)) }));
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

  const decisionText = (kind: string | undefined, summary: string): string => {
    if (summary.length > 0) return summary;
    const key = `chat.decision.${kind ?? "other"}` as MessageKey;
    const text = planText(key);
    return text === key ? planText("chat.decision.other") : text;
  };

  const startStream = (projectId: string, conversationId: string): void => {
    unsubscribe?.();
    // Plan vu dans l'historique : encore à valider seulement si rien n'a suivi
    // et si ses tâches existent toujours (un plan refusé ne doit pas revenir).
    let replayedPlan: { count: number } | null = null;
    unsubscribe = streamConversation(conversationId, {
      onToken: (text) => {
        if (text.length === 0) return;
        set((state) => ({
          streamBuffer: state.streamBuffer + text,
          streaming: true,
        }));
      },
      onReplayEnd: () => {
        const plan = replayedPlan;
        if (plan === null) return;
        void engine
          .listTasks(projectId)
          .then((tasks) => {
            const waiting = tasks.some(
              (task) => task.conversation_id === conversationId && task.status === "todo",
            );
            if (waiting && get().conversationId === conversationId) set({ pendingPlan: plan });
          })
          .catch(() => {
            /* sans la liste, on ne propose pas de valider un plan incertain */
          });
      },
      onAgentStatus: (event) => {
        replayedPlan = null;
        pushEvent({
          kind: "agent_status",
          agent: event.agent,
          status: event.status,
          summary: event.task ?? "",
        });
        bumpUnderstanding(event.progress);
      },
      onDecision: (event) => {
        const isPlan = event.kind === "plan_tasks";
        const count = event.count ?? 0;
        pushEvent({
          kind: "decision",
          agent: event.agent ?? null,
          status: null,
          // Texte lisible et localisé (jamais le JSON brut de l'événement).
          summary: isPlan
            ? planText("chat.plan.ready", { count })
            : decisionText(event.kind, event.summary),
        });
        if (isPlan) {
          if (event.historical === true) replayedPlan = { count };
          else set({ pendingPlan: { count } });
        }
        if (event.kind === "changes_proposed" && event.historical !== true) {
          set((state) => ({ changesVersion: state.changesVersion + 1 }));
        }
        if (event.actionId !== undefined) {
          set((state) => ({
            pendingActions: state.pendingActions.filter((a) => a.action_id !== event.actionId),
          }));
        }
        bumpUnderstanding(event.progress);
      },
      onActionRequest: (event) => {
        pushEvent({
          kind: "action_request",
          agent: event.agent ?? null,
          status: null,
          summary: event.summary,
        });
        const { action_id: actionId, tool, server } = event;
        if (event.historical !== true && actionId !== undefined && tool !== undefined && server !== undefined) {
          const action: PendingAction = {
            action_id: actionId,
            agent: event.agent ?? "",
            server,
            tool,
            arguments: event.arguments ?? "{}",
          };
          set((state) => ({ pendingActions: [...state.pendingActions, action] }));
        }
      },
      onDone: () => {
        set((state) => ({ pendingActions: [], changesVersion: state.changesVersion + 1 }));
        // Re-fetch rather than flush the raw streamed buffer: the stored
        // message may differ from what was streamed (e.g. the PM's
        // discuss-mode reply has a machine-readable <checklist> block
        // stripped server-side only from the persisted text, not from the
        // live token stream).
        engine
          .listMessages(conversationId)
          .then((messages) => {
            if (get().conversationId !== conversationId) return; // autre projet ouvert
            set({ messages, streamBuffer: "", streaming: false, sending: false });
          })
          .catch(() => {
            if (get().conversationId !== conversationId) return;
            flushBuffer();
            set({ sending: false });
          });
      },
      onError: (humanMessage, info) => {
        if (info.midRun) {
          // Une tâche a échoué, l'équipe continue : la saisie reste verrouillée.
          set({ streamError: humanMessage });
          return;
        }
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
    pendingPlan: null,
    failedDraft: null,
    pendingActions: [],
    changesVersion: 0,
    workspaceRequired: false,
    expertSubmode: defaultPrefs().expertSubmode,
    consumeFailedDraft: () => {
      set({ failedDraft: null });
    },
    mode: defaultPrefs().mode,
    execution: defaultPrefs().execution,
    model: defaultPrefs().model,
    effort: defaultPrefs().effort,

    openForProject: async (projectId) => {
      unsubscribe?.();
      unsubscribe = null;
      openSeq += 1;
      const seq = openSeq;
      useUiStore.getState().setLastProject(projectId);
      // Préférences propres au projet si connues ; sinon on conserve celles en
      // mémoire (ex. choix fait sur l'accueil avant la création du projet).
      const state = get();
      const prefs: ChatPrefs =
        prefsByProject.get(projectId) ?? {
          mode: state.mode,
          execution: state.execution,
          expertSubmode: state.expertSubmode,
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
        pendingPlan: null,
        pendingActions: [],
        workspaceRequired: false,
        mode: prefs.mode,
        execution: prefs.execution,
        expertSubmode: prefs.expertSubmode,
        model: prefs.model,
        effort: prefs.effort,
      });
      try {
        const conversations = await engine.listConversations(projectId);
        if (seq !== openSeq) return; // navigation entre-temps
        const first = conversations[0];
        if (first === undefined) {
          // Aucune conversation : elle sera créée au premier message.
          set({ messagesStatus: "ready" });
          return;
        }
        set({ conversationId: first.id });
        const messages = await engine.listMessages(first.id);
        if (seq !== openSeq) return;
        set({ messages, messagesStatus: "ready" });
        startStream(projectId, first.id);
        // Un outil attendait déjà une décision avant la réouverture.
        void engine
          .listActions(first.id)
          .then((pendingActions) => {
            if (seq === openSeq) set({ pendingActions });
          })
          .catch(() => undefined);
      } catch (err) {
        if (seq !== openSeq) return;
        set({ messagesStatus: "error", error: toHumanMessage(err) });
      }
    },

    send: async (content, overrides) => {
      const trimmed = content.trim();
      const { projectId, sending, pendingPlan } = get();
      if (trimmed.length === 0 || projectId === null || sending) return;
      // Un nouveau message remplace la proposition de plan en attente.
      set({
        sending: true,
        streamError: null,
        pendingPlan: null,
        failedDraft: null,
        workspaceRequired: false,
      });
      const seq = openSeq;
      // Lus avant toute attente : ce sont les réglages du projet qui envoie.
      const { model, effort } = get();
      const mode = overrides?.mode ?? get().mode;
      const execution = overrides?.execution ?? get().execution;
      const expertSubmode = overrides?.expertSubmode ?? get().expertSubmode;
      localSeq += 1;
      const userMessage: Message = {
        id: `local-${String(localSeq)}`,
        role: "user",
        content: trimmed,
      };
      try {
        let conversationId = get().conversationId;
        if (conversationId === null) {
          const conversation = await engine.createConversation(projectId);
          conversationId = conversation.id;
          // Projet changé pendant la création : le message part dans SON projet,
          // sans rien écrire dans l'état de celui qui est maintenant ouvert.
          if (seq === openSeq) {
            set({ conversationId });
            startStream(projectId, conversationId);
          }
        }
        if (seq === openSeq) set((state) => ({ messages: [...state.messages, userMessage] }));
        await engine.sendMessage(conversationId, trimmed, {
          mode,
          execution,
          // Le moteur refuse « expert » sans sous-mode (erreur 422).
          ...(execution === "expert" ? { expertSubmode } : {}),
          ...(model !== null ? { model } : {}),
          effort,
        });
        // `sending` repasse à false sur l'événement done/error du flux.
      } catch (err) {
        if (seq !== openSeq) return;
        const needsFolder = (err as { code?: unknown }).code === "workspace_required";
        set((state) => ({
          sending: false,
          // Le bandeau du dossier explique déjà ce qu'il faut faire.
          streamError: needsFolder ? null : toHumanMessage(err),
          workspaceRequired: needsFolder,
          // Le plan reste à valider une fois le dossier relié.
          pendingPlan: needsFolder ? pendingPlan : null,
          failedDraft: overrides === undefined ? trimmed : null,
          messages: state.messages.filter((m) => m.id !== userMessage.id),
        }));
      }
    },

    cancel: async () => {
      const { conversationId } = get();
      if (conversationId === null) return;
      try {
        const { cancelled } = await engine.cancelRun(conversationId);
        // Sinon, l'événement de fin du flux débloque la saisie.
        if (!cancelled) set({ sending: false });
      } catch (err) {
        set({ streamError: toHumanMessage(err) });
      }
    },

    decideAction: async (actionId, approved) => {
      const { conversationId } = get();
      if (conversationId === null) return;
      set((state) => ({
        pendingActions: state.pendingActions.filter((a) => a.action_id !== actionId),
      }));
      try {
        await engine.decideAction(conversationId, actionId, approved);
      } catch (err) {
        set({ streamError: toHumanMessage(err) });
      }
    },

    dismissWorkspaceRequest: () => {
      set({ workspaceRequired: false });
    },

    approvePlan: async (submode = "analyse") => {
      if (get().pendingPlan === null) return;
      await get().send(
        planText(submode === "complet" ? "chat.plan.executeMessage" : "chat.plan.approveMessage"),
        // Le mode reste souvent sur « Plan » : ce tour-ci exécute, il ne replanifie pas.
        { mode: "discuss", execution: "expert", expertSubmode: submode },
      );
    },

    rejectPlan: async () => {
      const { conversationId } = get();
      if (conversationId === null || rejectingPlan) return;
      rejectingPlan = true;
      try {
        await engine.rejectPlan(conversationId);
        set({ pendingPlan: null });
        pushEvent({
          kind: "decision",
          agent: null,
          status: null,
          summary: planText("chat.plan.rejected"),
        });
      } catch (err) {
        set({ streamError: toHumanMessage(err) });
      } finally {
        rejectingPlan = false;
      }
    },

    setMode: (mode) => {
      rememberPrefs(get().projectId, { mode });
      set({ mode });
    },
    setExecution: (execution, expertSubmode) => {
      const submode = expertSubmode ?? get().expertSubmode;
      rememberPrefs(get().projectId, { execution, expertSubmode: submode });
      set({ execution, expertSubmode: submode });
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
      openSeq += 1;
      unsubscribe?.();
      unsubscribe = null;
      set({ streaming: false, sending: false });
    },
  };
});

// « Effort par défaut » s'applique tout de suite, pas au prochain démarrage.
useSettingsStore.subscribe((state, previous) => {
  if (state.defaultEffort === previous.defaultEffort) return;
  for (const [projectId, prefs] of prefsByProject) {
    prefsByProject.set(projectId, { ...prefs, effort: state.defaultEffort });
  }
  useChatStore.setState({ effort: state.defaultEffort });
});
