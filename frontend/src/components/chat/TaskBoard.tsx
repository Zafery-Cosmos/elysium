import { useCallback, useEffect, useState, type FormEvent } from "react";
import { engine, toHumanMessage } from "../../services/engine";
import { useT, type MessageKey } from "../../i18n";
import { Button } from "../ui/Button";
import { Input } from "../ui/Input";
import { Modal } from "../ui/Modal";
import type { Agent, BoardTask, TaskStatus } from "../../types/engine";

const COLUMNS: Array<{ status: TaskStatus; label: MessageKey }> = [
  { status: "todo", label: "board.todo" },
  { status: "in_progress", label: "board.inProgress" },
  { status: "done", label: "board.done" },
  { status: "blocked", label: "board.blocked" },
];

const FIELD =
  "h-8 rounded-md border border-rule bg-paper px-2 text-xs text-ink outline-none focus:border-rule-strong";

/** Tableau des tâches du projet : ce que l'équipe exécute, modifiable à la main. */
export function TaskBoard({
  projectId,
  open,
  onClose,
}: {
  projectId: string;
  open: boolean;
  onClose: () => void;
}) {
  const t = useT();
  const [tasks, setTasks] = useState<BoardTask[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [title, setTitle] = useState("");
  const [role, setRole] = useState("");
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    engine.listBoard(projectId).then(setTasks).catch((err: unknown) => {
      setError(toHumanMessage(err));
    });
  }, [projectId]);

  useEffect(() => {
    if (!open) return;
    refresh();
    engine
      .listAgents(projectId)
      .then((list) => {
        setAgents(list);
        setRole((current) => current || (list.find((a) => a.name === "backend")?.name ?? list[0]?.name ?? ""));
      })
      .catch(() => undefined);
  }, [open, projectId, refresh]);

  const act = (action: Promise<unknown>): void => {
    setError(null);
    action.then(refresh).catch((err: unknown) => {
      setError(toHumanMessage(err));
    });
  };

  const add = (e: FormEvent): void => {
    e.preventDefault();
    const clean = title.trim();
    if (clean.length === 0 || role.length === 0) return;
    act(engine.createTask(projectId, { title: clean, agent_role: role }));
    setTitle("");
  };

  return (
    <Modal open={open} size="wide" title={t("board.title")} onClose={onClose}>
      <form onSubmit={add} className="mb-4 flex flex-wrap items-center gap-2">
        <div className="min-w-48 flex-1">
          <Input
            aria-label={t("board.new")}
            placeholder={t("board.new")}
            value={title}
            maxLength={300}
            onChange={(e) => {
              setTitle(e.target.value);
            }}
          />
        </div>
        <select
          aria-label={t("board.agent")}
          value={role}
          onChange={(e) => {
            setRole(e.target.value);
          }}
          className={FIELD}
        >
          {agents.map((agent) => (
            <option key={agent.name} value={agent.name}>
              {agent.name}
            </option>
          ))}
        </select>
        <Button type="submit" variant="primary" disabled={title.trim().length === 0}>
          {t("board.add")}
        </Button>
      </form>
      {error !== null && (
        <p role="alert" className="mb-3 text-xs text-danger">
          {error}
        </p>
      )}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {COLUMNS.map((column) => {
          const items = tasks.filter((task) => task.status === column.status);
          return (
            <section key={column.status} aria-label={t(column.label)} className="min-w-0">
              <h3 className="mb-2 text-xs font-medium text-muted">
                {t(column.label)} · {items.length}
              </h3>
              <ul className="flex flex-col gap-2">
                {items.map((task) => (
                  <li key={task.id} className="rounded-md border border-rule bg-paper-2/50 p-2.5">
                    <p className="break-words text-sm text-ink">{task.title}</p>
                    <p className="mt-0.5 truncate text-xs text-neutral">{task.agent_role}</p>
                    {task.status === "blocked" && task.result_summary !== null && (
                      <p className="mt-1 line-clamp-3 break-words text-xs text-danger">
                        {task.result_summary}
                      </p>
                    )}
                    <div className="mt-2 flex items-center justify-between gap-2">
                      <select
                        aria-label={t("board.status", { title: task.title })}
                        value={task.status}
                        onChange={(e) => {
                          act(engine.updateTask(task.id, { status: e.target.value as TaskStatus }));
                        }}
                        className={FIELD}
                      >
                        {COLUMNS.map((option) => (
                          <option key={option.status} value={option.status}>
                            {t(option.label)}
                          </option>
                        ))}
                      </select>
                      <button
                        type="button"
                        onClick={() => {
                          act(engine.deleteTask(task.id));
                        }}
                        className="rounded-sm text-xs text-neutral underline-offset-2 hover:text-danger hover:underline"
                      >
                        {t("common.delete")}
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
      </div>
    </Modal>
  );
}
