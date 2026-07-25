import { useMemo } from "react";
import type { TeamEvent } from "../../stores/chat";
import { agentStatusMeta, roleLabel } from "../../lib/labels";
import { Badge } from "../ui/Badge";

function eventTime(at: number): string {
  return new Date(at).toLocaleTimeString("fr-FR", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function EventRow({ event }: { event: TeamEvent }) {
  const agent = roleLabel(event.agent) ?? event.agent;
  if (event.kind === "agent_status") {
    const meta = agentStatusMeta(event.status ?? undefined);
    return (
      <li className="flex animate-fade-in flex-col gap-1 py-2.5">
        <div className="flex items-center justify-between gap-2">
          <span className="truncate font-mono text-xs text-muted">{agent}</span>
          <Badge tone={meta.tone} live={meta.live}>
            {meta.label}
          </Badge>
        </div>
        {event.summary.length > 0 && (
          <p className="text-xs text-neutral">{event.summary}</p>
        )}
      </li>
    );
  }
  return (
    <li className="flex animate-fade-in flex-col gap-1 py-2.5">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate font-mono text-xs text-muted">
          {agent ?? "Équipe"}
        </span>
        <span className="shrink-0 text-xs text-neutral">
          {eventTime(event.at)}
        </span>
      </div>
      <p className="text-sm text-ink">
        {event.kind === "action_request" && (
          <span className="mr-1.5 rounded-sm bg-paper-3 px-1.5 py-0.5 font-mono text-xs text-ink">
            action
          </span>
        )}
        {event.summary}
      </p>
    </li>
  );
}

export function TeamActivity({ events }: { events: TeamEvent[] }) {
  // Fil lisible : décisions et résumés, du plus récent au plus ancien.
  const visible = useMemo(() => [...events].reverse(), [events]);

  return (
    <aside
      aria-label="Activité de l'équipe"
      className="flex w-72 shrink-0 flex-col overflow-hidden border-l border-rule bg-paper"
    >
      <div className="flex h-12 shrink-0 items-center border-b border-rule px-4">
        <h2 className="text-sm font-medium text-muted">Activité de l'équipe</h2>
      </div>
      {visible.length === 0 ? (
        <p className="px-4 py-6 text-xs text-neutral">
          Les décisions et changements d'état des agents apparaîtront ici dès
          que l'équipe se mettra au travail.
        </p>
      ) : (
        <ul className="flex-1 divide-y divide-rule overflow-y-auto px-4">
          {visible.map((event) => (
            <EventRow key={event.id} event={event} />
          ))}
        </ul>
      )}
    </aside>
  );
}
