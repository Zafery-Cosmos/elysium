import { useEffect } from "react";
import { Link } from "react-router-dom";
import { PageHeader } from "../components/layout/PageHeader";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorState } from "../components/ui/ErrorState";
import { LoadingBlock } from "../components/ui/Spinner";
import { ProgressBar } from "../components/ui/ProgressBar";
import { useProjectsStore } from "../stores/projects";
import { useAgentsStore } from "../stores/agents";
import { useModelsStore } from "../stores/models";
import { agentStatusMeta } from "../lib/labels";
import { useT, type TFunction } from "../i18n";
import { normalizeProgress } from "../lib/format";
import type { Project } from "../types/engine";

function StatTile({
  label,
  value,
  caption,
  delay = 0,
}: {
  label: string;
  value: string;
  caption?: string;
  delay?: number;
}) {
  return (
    <div
      style={{ animationDelay: `${delay}ms` }}
      className="card-lift animate-rise-in rounded-lg border border-rule bg-paper-2/50 px-5 py-4 hover:border-rule-strong"
    >
      <p className="text-xs text-neutral">{label}</p>
      <p className="mt-1.5 font-mono text-xl text-ink">{value}</p>
      {caption !== undefined && (
        <p className="mt-1 text-xs text-neutral">{caption}</p>
      )}
    </div>
  );
}

function ProjectRow({
  project,
  delay = 0,
  t,
}: {
  project: Project;
  delay?: number;
  t: TFunction;
}) {
  const progress = normalizeProgress(project.progress);
  return (
    <Link
      to={`/chat/${encodeURIComponent(project.id)}`}
      style={{ animationDelay: `${delay}ms` }}
      className="group card-lift animate-rise-in flex flex-col gap-2.5 rounded-lg border border-rule bg-paper-2/50 px-5 py-4 hover:border-rule-strong hover:bg-paper-2"
    >
      <div className="flex items-baseline justify-between gap-3">
        <span className="truncate text-sm font-medium text-ink">
          {project.name}
        </span>
        {progress !== null && (
          <span className="shrink-0 font-mono text-xs text-neutral">
            {Math.round(progress * 100)} %
          </span>
        )}
      </div>
      {progress !== null ? (
        <ProgressBar
          value={progress}
          label={t("dash.projects.progressOf", { name: project.name })}
        />
      ) : (
        <p className="text-xs text-neutral">
          {t("dash.projects.progressUnknown")}
        </p>
      )}
    </Link>
  );
}

export function Dashboard() {
  const t = useT();
  const projects = useProjectsStore();
  const agents = useAgentsStore();
  const models = useModelsStore();

  useEffect(() => {
    void projects.fetch();
    void agents.fetch();
    void models.fetch();
    // Chargement au montage uniquement.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const activeProjects = projects.projects.filter(
    (p) => p.status !== "archived",
  );
  const activeAgents = agents.agents.filter(
    (a) => agentStatusMeta(a.status).live,
  );
  const configuredProviders = models.providers.filter(
    (p) => p.configured === true,
  );

  const agentsValue =
    agents.status === "ready" ? String(activeAgents.length) : "—";
  const providersValue =
    models.status === "ready" ? String(configuredProviders.length) : "—";

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <PageHeader title={t("dash.title")} subtitle={t("dash.subtitle")} />
      <div className="flex flex-col gap-8 p-6">
        <section aria-label={t("dash.title")} className="animate-rise-in">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <StatTile
              label={t("dash.stat.projects")}
              value={
                projects.status === "ready"
                  ? String(activeProjects.length)
                  : "—"
              }
            />
            <StatTile
              label={t("dash.stat.agents")}
              value={agentsValue}
              delay={40}
              caption={
                agents.status === "ready"
                  ? t("dash.stat.agentsCaption", {
                      count: agents.agents.length,
                    })
                  : undefined
              }
            />
            <StatTile
              label={t("dash.stat.providers")}
              value={providersValue}
              delay={80}
            />
            <StatTile
              label={t("dash.stat.cost")}
              value="—"
              caption={t("common.soon")}
              delay={120}
            />
          </div>
        </section>

        <section
          aria-label={t("dash.projects.title")}
          className="flex animate-rise-in flex-col gap-3 [animation-delay:120ms]"
        >
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium text-muted">
              {t("dash.projects.title")}
            </h2>
            <Link
              to="/projects"
              className="rounded-sm text-sm text-ink underline-offset-2 hover:underline"
            >
              {t("dash.projects.all")}
            </Link>
          </div>

          {projects.status === "loading" && (
            <LoadingBlock label={t("dash.projects.loading")} />
          )}
          {projects.status === "error" && projects.error !== null && (
            <ErrorState
              message={projects.error}
              onRetry={() => void projects.fetch()}
            />
          )}
          {projects.status === "ready" && activeProjects.length === 0 && (
            <EmptyState
              title={t("dash.projects.empty.title")}
              description={t("dash.projects.empty.desc")}
              action={
                <Link
                  to="/"
                  className="inline-flex h-8 items-center rounded-md bg-ink px-3 text-sm font-medium text-paper transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)] hover:bg-ink/85"
                >
                  {t("nav.newConversation")}
                </Link>
              }
            />
          )}
          {projects.status === "ready" && activeProjects.length > 0 && (
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              {activeProjects.map((project, index) => (
                <ProjectRow
                  key={project.id}
                  project={project}
                  delay={Math.min(index, 8) * 40}
                  t={t}
                />
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
