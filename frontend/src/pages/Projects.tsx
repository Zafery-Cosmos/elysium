import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { PageHeader } from "../components/layout/PageHeader";
import { Button } from "../components/ui/Button";
import { Modal } from "../components/ui/Modal";
import { TextAreaField, TextField } from "../components/ui/Field";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorState } from "../components/ui/ErrorState";
import { LoadingBlock } from "../components/ui/Spinner";
import { IconPlus } from "../components/layout/icons";
import { useProjectsStore } from "../stores/projects";
import { useT } from "../i18n";
import { formatDate } from "../lib/format";
import type { Project } from "../types/engine";

function ProjectCard({ project }: { project: Project }) {
  const t = useT();
  const created = formatDate(project.created_at);
  return (
    <Link
      to={`/chat/${encodeURIComponent(project.id)}`}
      className="group flex flex-col gap-2 rounded-lg border border-rule bg-paper-2/50 px-5 py-4 transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)] hover:border-rule-strong hover:bg-paper-2"
    >
      <span className="text-sm font-medium text-ink">{project.name}</span>
      {project.description !== undefined &&
        project.description !== null &&
        project.description.length > 0 && (
          <p className="line-clamp-2 text-sm text-neutral">
            {project.description}
          </p>
        )}
      <div className="mt-1 flex items-center gap-3 text-xs text-neutral">
        {project.status !== undefined && (
          <span className="font-mono">{project.status}</span>
        )}
        {created !== null && <span>{t("projects.createdOn", { date: created })}</span>}
      </div>
    </Link>
  );
}

function NewProjectModal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const t = useT();
  const navigate = useNavigate();
  const create = useProjectsStore((s) => s.create);
  const creating = useProjectsStore((s) => s.creating);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);

  const onSubmit = async (e: FormEvent): Promise<void> => {
    e.preventDefault();
    if (name.trim().length === 0) return;
    setError(null);
    const project = await create({
      name: name.trim(),
      description: description.trim().length > 0 ? description.trim() : undefined,
    });
    if (project !== null) {
      onClose();
      void navigate(`/chat/${encodeURIComponent(project.id)}`);
    } else {
      setError(useProjectsStore.getState().error ?? t("home.createFailed"));
    }
  };

  return (
    <Modal open={open} title={t("projects.new")} onClose={onClose}>
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          void onSubmit(e);
        }}
      >
        <TextField
          label={t("agents.field.name")}
          value={name}
          onChange={(e) => {
            setName(e.target.value);
          }}
          placeholder={t("projects.field.name.placeholder")}
          required
          maxLength={120}
        />
        <TextAreaField
          label={t("projects.field.description")}
          value={description}
          onChange={(e) => {
            setDescription(e.target.value);
          }}
          placeholder={t("projects.field.description.placeholder")}
          hint={t("projects.field.description.hint")}
        />
        {error !== null && (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            type="submit"
            variant="primary"
            loading={creating}
            disabled={name.trim().length === 0}
          >
            {t("projects.submit")}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

export function Projects() {
  const t = useT();
  const { projects, status, error, fetch } = useProjectsStore();
  const [modalOpen, setModalOpen] = useState(false);

  useEffect(() => {
    void fetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <PageHeader
        title={t("projects.title")}
        action={
          <Button
            variant="primary"
            onClick={() => {
              setModalOpen(true);
            }}
          >
            <IconPlus width={14} height={14} />
            {t("projects.new")}
          </Button>
        }
      />
      <div className="p-6">
        {status === "loading" && <LoadingBlock label={t("dash.projects.loading")} />}
        {status === "error" && error !== null && (
          <ErrorState message={error} onRetry={() => void fetch()} />
        )}
        {status === "ready" && projects.length === 0 && (
          <EmptyState
            title={t("projects.empty.title")}
            description={t("projects.empty.desc")}
            action={
              <Button
                variant="primary"
                onClick={() => {
                  setModalOpen(true);
                }}
              >
                <IconPlus width={14} height={14} />
                {t("projects.new")}
              </Button>
            }
          />
        )}
        {status === "ready" && projects.length > 0 && (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            {projects.map((project) => (
              <ProjectCard key={project.id} project={project} />
            ))}
          </div>
        )}
      </div>
      <NewProjectModal
        open={modalOpen}
        onClose={() => {
          setModalOpen(false);
        }}
      />
    </div>
  );
}
