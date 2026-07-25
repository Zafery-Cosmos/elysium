import { useEffect, useRef } from "react";
import type { Message } from "../../types/engine";
import { roleLabel } from "../../lib/labels";
import { cx } from "../../lib/cx";
import { Spinner } from "../ui/Spinner";

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user";
  const agent = roleLabel(message.agent);
  return (
    <div className={cx("flex animate-fade-in", isUser && "justify-end")}>
      <div
        className={cx(
          "max-w-[52rem] min-w-0",
          isUser
            ? "rounded-lg bg-paper-3 px-4 py-2.5"
            : "border-l-2 border-rule py-1 pl-4",
        )}
      >
        {!isUser && (
          <p className="mb-1 font-mono text-xs text-accent">
            {agent ?? "Équipe Elysium"}
          </p>
        )}
        <p className="text-sm whitespace-pre-wrap text-ink">{message.content}</p>
      </div>
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
    <div className="flex">
      <div className="max-w-[52rem] min-w-0 border-l-2 border-accent-dim py-1 pl-4">
        <p className="mb-1 flex items-center gap-2 font-mono text-xs text-accent">
          {roleLabel(agent) ?? "Équipe Elysium"}
          <Spinner className="size-3 text-accent" />
        </p>
        <p className="text-sm whitespace-pre-wrap text-ink">
          {buffer}
          <span aria-hidden="true" className="ml-0.5 inline-block h-3.5 w-1.5 translate-y-0.5 animate-pulse-dot bg-accent" />
        </p>
      </div>
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
    <div className="flex flex-col gap-5 px-6 py-6">
      {messages.map((message) => (
        <MessageBubble key={message.id} message={message} />
      ))}
      {streaming && streamBuffer.length > 0 && (
        <StreamingBubble buffer={streamBuffer} agent={streamAgent} />
      )}
      {waiting && !streaming && (
        <div className="flex items-center gap-2 pl-4 text-sm text-neutral" role="status">
          <Spinner />
          <span>L'équipe examine votre demande…</span>
        </div>
      )}
      <div ref={endRef} />
    </div>
  );
}
