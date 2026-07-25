import { useEffect } from "react";
import { PageHeader } from "../components/layout/PageHeader";
import { Badge } from "../components/ui/Badge";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorState } from "../components/ui/ErrorState";
import { LoadingBlock } from "../components/ui/Spinner";
import { useAgentsStore } from "../stores/agents";
import { useUiStore } from "../stores/ui";
import { agentStatusMeta, roleLabel } from "../lib/labels";
import type { Agent } from "../types/engine";

function AgentCard({
  agent,
  advanced,
  delay = 0,
}: {
  agent: Agent;
  advanced: boolean;
  delay?: number;
}) {
  const meta = agentStatusMeta(agent.status);
  const role = roleLabel(agent.role);
  return (
    <article
      style={{ animationDelay: `${delay}ms` }}
      className="card-lift flex animate-rise-in flex-col gap-3 rounded-lg border border-rule bg-paper-2/50 px-5 py-4 hover:border-rule-strong"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="truncate text-sm font-medium text-ink">
            {agent.name}
          </h2>
          {role !== null && (
            <p className="mt-0.5 text-xs text-neutral">{role}</p>
          )}
        </div>
        <Badge tone={meta.tone} live={meta.live}>
          {meta.label}
        </Badge>
      </div>
      {agent.current_task !== undefined &&
      agent.current_task !== null &&
      agent.current_task.length > 0 ? (
        <p className="text-sm text-muted">{agent.current_task}</p>
      ) : (
        <p className="text-sm text-neutral">Aucune tâche en cours.</p>
      )}
      {advanced &&
        agent.model !== undefined &&
        agent.model !== null &&
        agent.model.length > 0 && (
          <p className="font-mono text-xs text-neutral">{agent.model}</p>
        )}
    </article>
  );
}

export function Agents() {
  const { agents, status, error, fetch } = useAgentsStore();
  const mode = useUiStore((s) => s.mode);

  useEffect(() => {
    void fetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <PageHeader
        title="Agents"
        subtitle="L'équipe qui construit vos projets"
      />
      <div className="p-6">
        {status === "loading" && <LoadingBlock label="Chargement de l'équipe…" />}
        {status === "error" && error !== null && (
          <ErrorState message={error} onRetry={() => void fetch()} />
        )}
        {status === "ready" && agents.length === 0 && (
          <EmptyState
            title="Aucun agent actif"
            description="L'équipe se constitue à l'ouverture d'un projet : chef de projet, architecte, développeurs, QA…"
          />
        )}
        {status === "ready" && agents.length > 0 && (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            {agents.map((agent, index) => (
              <AgentCard
                key={agent.id ?? `${agent.name}-${String(index)}`}
                agent={agent}
                advanced={mode === "advanced"}
                delay={Math.min(index, 8) * 40}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
