import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { MessageThread } from "../components/chat/MessageThread";
import { ChatInput } from "../components/chat/ChatInput";
import { TeamActivity } from "../components/chat/TeamActivity";
import { UnderstandingIndicator } from "../components/chat/UnderstandingIndicator";
import { ErrorState } from "../components/ui/ErrorState";
import { LoadingBlock } from "../components/ui/Spinner";
import { IconArrowLeft } from "../components/layout/icons";
import { useChatStore } from "../stores/chat";
import { engine } from "../services/engine";
import type { Project } from "../types/engine";

export function ProjectView() {
  const { id } = useParams<{ id: string }>();
  const chat = useChatStore();
  const [project, setProject] = useState<Project | null>(null);

  useEffect(() => {
    if (id === undefined) return;
    setProject(null);
    engine
      .getProject(id)
      .then(setProject)
      .catch(() => {
        // Non bloquant : la conversation reste utilisable sans les détails.
      });
    void useChatStore.getState().openForProject(id);
    return () => {
      useChatStore.getState().close();
    };
  }, [id]);

  const liveAgent = useMemo(() => {
    const last = [...chat.events]
      .reverse()
      .find((e) => e.kind === "agent_status" && e.status === "generating");
    return last?.agent ?? null;
  }, [chat.events]);

  if (id === undefined) return null;

  const waiting = chat.sending && chat.streamBuffer.length === 0;

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-rule px-6">
        <Link
          to="/projects"
          aria-label="Retour aux projets"
          className="grid size-7 place-items-center rounded-md text-neutral transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)] hover:bg-paper-2 hover:text-muted"
        >
          <IconArrowLeft width={16} height={16} />
        </Link>
        <h1 className="truncate text-md">
          {project?.name ?? "Projet"}
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

      <div className="flex min-h-0 flex-1">
        <section
          aria-label="Conversation avec l'équipe"
          className="flex min-w-0 flex-1 flex-col"
        >
          <div className="min-h-0 flex-1 overflow-y-auto">
            {chat.messagesStatus === "loading" && (
              <LoadingBlock label="Ouverture de la conversation…" />
            )}
            {chat.messagesStatus === "error" && chat.error !== null && (
              <div className="p-6">
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
                <div className="flex h-full flex-col items-start justify-center gap-2 px-10">
                  <h2 className="text-lg text-ink">
                    Par quoi commence-t-on ?
                  </h2>
                  <p className="max-w-md text-sm text-neutral">
                    Décrivez votre idée en une phrase. Le chef de projet
                    posera les bonnes questions, puis l'équipe se met au
                    travail — vous validez chaque étape importante.
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

          {chat.streamError !== null && (
            <p
              role="alert"
              className="border-t border-danger/30 bg-danger/5 px-6 py-2 text-sm text-danger"
            >
              {chat.streamError}
            </p>
          )}

          <ChatInput
            onSend={(content) => {
              void useChatStore.getState().send(content);
            }}
            disabled={chat.messagesStatus !== "ready"}
            busy={chat.sending}
          />
        </section>

        <TeamActivity events={chat.events} />
      </div>
    </div>
  );
}
