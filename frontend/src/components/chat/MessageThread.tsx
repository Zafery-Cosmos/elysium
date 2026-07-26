import { useEffect, useRef } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Message } from "../../types/engine";
import { roleLabelKey } from "../../lib/labels";
import { useT } from "../../i18n";
import { Spinner } from "../ui/Spinner";

/** Éléments markdown restylés pour coller au gabarit typographique du chat. */
const MARKDOWN_COMPONENTS: Components = {
  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
  strong: ({ children }) => <strong className="font-semibold text-ink">{children}</strong>,
  ul: ({ children }) => <ul className="mb-2 list-disc space-y-0.5 pl-5 last:mb-0">{children}</ul>,
  ol: ({ children }) => (
    <ol className="mb-2 list-decimal space-y-0.5 pl-5 last:mb-0">{children}</ol>
  ),
  li: ({ children }) => <li>{children}</li>,
  a: ({ children, href }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="underline underline-offset-2 hover:text-ink"
    >
      {children}
    </a>
  ),
  code: ({ children }) => (
    <code className="rounded-sm bg-paper-3 px-1 py-0.5 font-mono text-[0.85em]">{children}</code>
  ),
};

function Markdown({ text }: { text: string }) {
  return (
    <div className="text-sm text-ink">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
        {text}
      </ReactMarkdown>
    </div>
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
      <Markdown text={message.content} />
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
      <div className="flex items-end gap-0.5">
        <Markdown text={buffer} />
        <span
          aria-hidden="true"
          className="mb-1 inline-block h-3.5 w-1.5 shrink-0 animate-pulse-dot bg-ink"
        />
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
