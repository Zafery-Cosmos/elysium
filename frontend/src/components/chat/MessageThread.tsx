import { useEffect, useRef } from "react";
import type { Message } from "../../types/engine";
import { roleLabel } from "../../lib/labels";
import { Spinner } from "../ui/Spinner";

function MessageBubble({ message }: { message: Message }) {
  if (message.role === "user") {
    return (
      <div className="flex animate-rise-in justify-end">
        <div className="max-w-[85%] min-w-0 rounded-2xl bg-paper-3 px-4 py-2.5">
          <p className="text-sm whitespace-pre-wrap text-ink">
            {message.content}
          </p>
        </div>
      </div>
    );
  }
  const agent = roleLabel(message.agent);
  return (
    <div className="min-w-0 animate-rise-in">
      <p className="mb-1 text-xs text-neutral">{agent ?? "Équipe Elysium"}</p>
      <p className="text-sm whitespace-pre-wrap text-ink">{message.content}</p>
    </div>
  );
}

function StreamingBubble({
  buffer,
  agent,
}: {
  buffer: string;
  agent: string | null;
}) {
  return (
    <div className="min-w-0">
      <p className="mb-1 flex items-center gap-2 text-xs text-neutral">
        {roleLabel(agent) ?? "Équipe Elysium"}
        <Spinner className="size-3 text-neutral" />
      </p>
      <p className="text-sm whitespace-pre-wrap text-ink">
        {buffer}
        <span
          aria-hidden="true"
          className="ml-0.5 inline-block h-3.5 w-1.5 translate-y-0.5 animate-pulse-dot bg-ink"
        />
      </p>
    </div>
  );
}

export function MessageThread({
  messages,
  streaming,
  streamBuffer,
  streamAgent,
  waiting,
}: {
  messages: Message[];
  streaming: boolean;
  streamBuffer: string;
  streamAgent: string | null;
  /** Message envoyé, aucun token encore reçu. */
  waiting: boolean;
}) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [messages.length, streamBuffer]);

  return (
    <div className="flex flex-col gap-6 py-6">
      {messages.map((message) => (
        <MessageBubble key={message.id} message={message} />
      ))}
      {streaming && streamBuffer.length > 0 && (
        <StreamingBubble buffer={streamBuffer} agent={streamAgent} />
      )}
      {waiting && !streaming && (
        <div className="flex items-center gap-2 text-sm text-neutral" role="status">
          <Spinner />
          <span>L'équipe examine votre demande…</span>
        </div>
      )}
      <div ref={endRef} />
    </div>
  );
}
