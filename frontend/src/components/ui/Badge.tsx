import { cx } from "../../lib/cx";
import type { Tone } from "../../lib/labels";

const TONES: Record<Tone, { text: string; dot: string }> = {
  accent: { text: "text-accent", dot: "bg-accent" },
  ok: { text: "text-ok", dot: "bg-ok" },
  danger: { text: "text-danger", dot: "bg-danger" },
  info: { text: "text-info", dot: "bg-info" },
  muted: { text: "text-neutral", dot: "bg-neutral" },
};

export function Badge({
  tone = "muted",
  live = false,
  children,
}: {
  tone?: Tone;
  live?: boolean;
  children: string;
}) {
  const meta = TONES[tone];
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1.5 rounded-full border border-rule px-2 py-0.5 text-xs",
        meta.text,
      )}
    >
      <span
        aria-hidden="true"
        className={cx(
          "size-1.5 rounded-full",
          meta.dot,
          live && "animate-pulse-dot",
        )}
      />
      {children}
    </span>
  );
}
