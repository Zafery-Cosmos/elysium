import { useEffect, useMemo, useRef } from "react";
import type { Message } from "../../types/engine";
import { roleLabelKey } from "../../lib/labels";
import { useT } from "../../i18n";
import { Spinner } from "../ui/Spinner";

/**
 * Nombre de segments (mots + espaces) animés en fin de flux. Au-delà,
 * le texte est rendu brut : le coût DOM reste borné quel que soit le
 * volume streamé, et les mots déjà posés ne rejouent jamais l'animation
 * (clés stables par index absolu).
 */
const ANIMATED_TAIL_SEGMENTS = 24;

function StreamingText({ buffer }: { buffer: string }) {
  const segments = useMemo(() => buffer.split(/(\s+)/), [buffer]);
  const start = Math.max(0, segments.length - ANIMATED_TAIL_SEGMENTS);
  const head = segments.slice(0, start).join("");
  const tail = segments.slice(start);
  return (
    <>
      {head}
      {tail.map((segment, i) =>
        segment.trim().length === 0 ? (
          <span key={start + i}>{segment}</span>
        ) : (
          <span key={start + i} className="inline animate-word-in">
            {segment}
          </span>
        ),
      )}
    </>
  );
}

function MessageBubble({ message }: { message: Message }) {
  const t = useT();
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
  const key = roleLabelKey(message.agent);
  const agent = key !== null ? t(key) : (message.agent ?? null);
  return (
    <div className="min-w-0 animate-rise-in">
      <p className="mb-1 text-xs text-neutral">{agent ?? t("chat.teamName")}</p>
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
  const t = useT();
  const key = roleLabelKey(agent);
  return (
    <div className="min-w-0">
      <p className="mb-1 flex items-center gap-2 text-xs text-neutral">
        {key !== null ? t(key) : (agent ?? t("chat.teamName"))}
        <Spinner className="size-3 text-neutral" />
      </p>
      <p className="text-sm whitespace-pre-wrap text-ink">
        <StreamingText buffer={buffer} />
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
  const t = useT();
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
          <span>{t("chat.examining")}</span>
        </div>
      )}
      <div ref={endRef} />
    </div>
  );
}
