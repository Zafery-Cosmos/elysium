import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { MessageThread } from "../components/chat/MessageThread";
import { ChatInput } from "../components/chat/ChatInput";
import { ChatControls } from "../components/chat/ChatControls";
import { Suggestions } from "../components/chat/Suggestions";
import { TeamActivity } from "../components/chat/TeamActivity";
import { UnderstandingIndicator } from "../components/chat/UnderstandingIndicator";
import { ErrorState } from "../components/ui/ErrorState";
import { LoadingBlock } from "../components/ui/Spinner";
import { useChatStore } from "../stores/chat";
import { useUiStore } from "../stores/ui";
import { useT } from "../i18n";
import { engine } from "../services/engine";
import type { Project } from "../types/engine";

interface ChatLocationState {
  /** Message saisi sur l'accueil, envoyé dès que la conversation est prête. */
  initialMessage?: string;
}

export function Chat() {
  const { id } = useParams<{ id: string }>();
  const location = useLocation();
  const navigate = useNavigate();
  const t = useT();
  const chat = useChatStore();
  const mode = useUiStore((s) => s.mode);
  const [project, setProject] = useState<Project | null>(null);
  const [draft, setDraft] = useState("");

  useEffect(() => {
    if (id === undefined) return;
    setProject(null);
    engine
      .getProject(id)
      .then(setProject)
      .catch(() => {
        // Non bloquant : la conversation reste utilisable sans les détails.
      });
    const state = location.state as ChatLocationState | null;
    const initial = state?.initialMessage;
    void useChatStore
      .getState()
      .openForProject(id)
      .then(() => {
        const current = useChatStore.getState();
        if (
          initial !== undefined &&
          initial.length > 0 &&
          current.projectId === id &&
          current.messagesStatus === "ready"
        ) {
          void current.send(initial);
        }
      });
    if (initial !== undefined) {
      // Efface l'état d'historique pour ne pas renvoyer le message au retour.
      void navigate(location.pathname, { replace: true, state: null });
    }
    return () => {
      useChatStore.getState().close();
    };
    // Ouverture pilotée par l'identifiant de projet uniquement.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const liveAgent = useMemo(() => {
    const last = [...chat.events]
      .reverse()
      .find((e) => e.kind === "agent_status" && e.status === "generating");
    return last?.agent ?? null;
  }, [chat.events]);

  if (id === undefined) return null;

  const waiting = chat.sending && chat.streamBuffer.length === 0;
  const showSuggestions =
    chat.messagesStatus === "ready" &&
    chat.messages.length === 0 &&
    !chat.streaming &&
    !chat.sending;

  return (
    <div className="flex h-full min-h-0">
      <section
        aria-label={t("chat.section")}
        className="flex min-w-0 flex-1 flex-col"
      >
        <header className="flex h-12 shrink-0 items-center gap-3 border-b border-rule px-6">
          <h1 className="truncate text-sm font-medium text-ink">
            {project?.name ?? t("chat.header.default")}
          </h1>
          {project?.description !== undefined &&
            project?.description !== null &&
            project.description.length > 0 && (
              <p className="hidden truncate text-sm text-neutral md:block">
                {project.description}
              </p>
            )}
        </header>

        <UnderstandingIndicator value={chat.understanding} />

        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-3xl px-6">
            {chat.messagesStatus === "loading" && (
              <LoadingBlock label={t("chat.opening")} />
            )}
            {chat.messagesStatus === "error" && chat.error !== null && (
              <div className="py-6">
                <ErrorState
                  message={chat.error}
                  onRetry={() => {
                    void useChatStore.getState().openForProject(id);
                  }}
                />
              </div>
            )}
            {chat.messagesStatus === "ready" &&
              chat.messages.length === 0 &&
              !chat.streaming &&
              !chat.sending && (
                <div className="flex flex-col items-start gap-2 py-16">
                  <h2 className="text-lg text-ink">{t("chat.start.title")}</h2>
                  <p className="max-w-md text-sm text-muted">
                    {t("chat.start.body")}
                  </p>
                </div>
              )}
            {chat.messagesStatus === "ready" &&
              (chat.messages.length > 0 || chat.streaming || chat.sending) && (
                <MessageThread
                  messages={chat.messages}
                  streaming={chat.streaming}
                  streamBuffer={chat.streamBuffer}
                  streamAgent={liveAgent}
                  waiting={waiting}
                />
              )}
          </div>
        </div>

        {chat.streamError !== null && (
          <div className="px-6 pb-2">
            <p
              role="alert"
              className="mx-auto w-full max-w-3xl rounded-md border border-danger/40 bg-paper px-4 py-2 text-sm text-danger"
            >
              {chat.streamError}
            </p>
          </div>
        )}

        <div className="shrink-0 px-6 pb-4">
          <div className="mx-auto w-full max-w-3xl">
            {showSuggestions && <Suggestions onPick={setDraft} />}
            <div className="mb-2">
              <ChatControls disabled={chat.messagesStatus !== "ready"} />
            </div>
            <ChatInput
              value={draft}
              onValueChange={setDraft}
              onSend={(content) => {
                void useChatStore.getState().send(content);
              }}
              disabled={chat.messagesStatus !== "ready"}
              busy={chat.sending}
            />
          </div>
        </div>
      </section>

      {mode === "advanced" && <TeamActivity events={chat.events} />}
    </div>
  );
}
