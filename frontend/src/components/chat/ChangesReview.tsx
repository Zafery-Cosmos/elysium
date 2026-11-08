import { useCallback, useEffect, useMemo, useState } from "react";
import { engine, toHumanMessage } from "../../services/engine";
import { ApplyError, writeChange } from "../../services/workspace";
import { diffLines, withContext } from "../../lib/diff";
import { useT, type TFunction } from "../../i18n";
import { cx } from "../../lib/cx";
import { Button } from "../ui/Button";
import { Modal } from "../ui/Modal";
import { Spinner } from "../ui/Spinner";
import type { FileChange, FileChangeDetail } from "../../types/engine";

function failureText(error: unknown, t: TFunction): string {
  if (error instanceof ApplyError) {
    switch (error.reason) {
      case "desktop_only":
        return t("changes.error.desktopOnly");
      case "no_scope":
        return t("changes.error.noScope", { path: error.message });
      case "conflict":
        return t("changes.error.conflict");
      case "denied":
        return t("changes.error.denied");
      default:
        return t("changes.error.failed");
    }
  }
  return toHumanMessage(error);
}

function DiffView({ detail }: { detail: FileChangeDetail }) {
  const t = useT();
  const rows = useMemo(() => {
    const full = diffLines(detail.base_content, detail.new_content);
    return full === null ? null : withContext(full);
  }, [detail]);
  if (rows === null) {
    return <p className="p-3 text-xs text-neutral">{t("changes.tooLarge")}</p>;
  }
  return (
    <div className="max-h-96 overflow-auto rounded-md border border-rule bg-paper-2 font-mono text-xs">
      <table className="w-full border-collapse">
        <tbody>
          {rows.map((row, index) =>
            row.kind === "skip" ? (
              <tr key={index}>
                <td colSpan={2} className="px-3 py-1 text-neutral">
                  {t("changes.skipped", { count: row.count })}
                </td>
              </tr>
            ) : (
              <tr
                key={index}
                className={cx(row.kind === "add" && "bg-ok/10", row.kind === "del" && "bg-danger/10")}
              >
                <td aria-hidden className="w-6 select-none px-2 text-center text-neutral">
                  {row.kind === "add" ? "+" : row.kind === "del" ? "−" : ""}
                </td>
                <td className="whitespace-pre px-2 text-ink">
                  <span className="sr-only">
                    {row.kind === "add" ? t("changes.added") : row.kind === "del" ? t("changes.removed") : ""}
                  </span>
                  {row.text}
                </td>
              </tr>
            ),
          )}
        </tbody>
      </table>
    </div>
  );
}

function ChangeRow({
  change,
  busy,
  error,
  onAccept,
  onReject,
  onRevert,
}: {
  change: FileChange;
  busy: boolean;
  error: string | null;
  onAccept: () => void;
  onReject: () => void;
  onRevert: () => void;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<FileChangeDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || detail !== null) return;
    engine.getChange(change.id).then(setDetail).catch((err: unknown) => {
      setLoadError(toHumanMessage(err));
    });
  }, [open, detail, change.id]);

  const applied = change.status === "applied";
  return (
    <li className="border-b border-rule py-2.5 last:border-b-0">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          aria-expanded={open}
          onClick={() => {
            setOpen((value) => !value);
          }}
          className="min-w-0 flex-1 truncate rounded-sm text-left font-mono text-xs text-ink underline-offset-2 hover:underline"
          title={change.path}
        >
          {change.path}
        </button>
        <span className="shrink-0 text-xs text-neutral">
          {change.action === "delete" ? t("changes.delete") : change.agent_name}
        </span>
        {busy && <Spinner className="size-3.5" />}
        {applied ? (
          <Button variant="ghost" onClick={onRevert} disabled={busy}>
            {t("changes.revert")}
          </Button>
        ) : (
          <>
            <Button variant="ghost" onClick={onReject} disabled={busy}>
              {t("changes.reject")}
            </Button>
            <Button variant="primary" onClick={onAccept} disabled={busy}>
              {t("changes.accept")}
            </Button>
          </>
        )}
      </div>
      {error !== null && (
        <p role="alert" className="mt-1.5 text-xs text-danger">
          {error}
        </p>
      )}
      {open && (
        <div className="mt-2">
          {loadError !== null && <p className="text-xs text-danger">{loadError}</p>}
          {detail !== null && <DiffView detail={detail} />}
        </div>
      )}
    </li>
  );
}

/** Bandeau + revue des fichiers proposés : rien n'est écrit sans « Accepter ». */
export function ChangesReview({
  projectId,
  version,
}: {
  projectId: string;
  /** Change quand l'équipe a proposé de nouveaux fichiers. */
  version: number;
}) {
  const t = useT();
  const [changes, setChanges] = useState<FileChange[]>([]);
  const [root, setRoot] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [busyIds, setBusyIds] = useState<ReadonlySet<string>>(new Set());
  const [errors, setErrors] = useState<Record<string, string>>({});

  const refresh = useCallback(() => {
    void engine.listChanges(projectId).then(setChanges).catch(() => undefined);
    void engine.getWorkspace(projectId).then((w) => {
      setRoot(w.root_path);
    }).catch(() => undefined);
  }, [projectId]);

  useEffect(refresh, [refresh, version]);

  const proposed = changes.filter((c) => c.status === "proposed");
  const applied = changes.filter((c) => c.status === "applied");

  const run = async (change: FileChange, action: () => Promise<void>): Promise<boolean> => {
    setBusyIds((ids) => new Set(ids).add(change.id));
    setErrors((all) => {
      const rest = { ...all };
      delete rest[change.id];
      return rest;
    });
    let ok = true;
    try {
      await action();
    } catch (error) {
      ok = false;
      setErrors((all) => ({ ...all, [change.id]: failureText(error, t) }));
    }
    setBusyIds((ids) => {
      const next = new Set(ids);
      next.delete(change.id);
      return next;
    });
    return ok;
  };

  const write = async (change: FileChange, direction: "apply" | "revert"): Promise<boolean> =>
    run(change, async () => {
      if (root === null) throw new ApplyError("no_scope", "");
      const detail = await engine.getChange(change.id);
      await writeChange(projectId, root, detail, direction);
      // Le disque a changé : l'état suit, même si l'interface se ferme ensuite.
      await engine.setChangeStatus(change.id, direction === "apply" ? "applied" : "reverted");
    });

  const reject = (change: FileChange): Promise<boolean> =>
    run(change, () => engine.setChangeStatus(change.id, "rejected").then(() => undefined));

  const acceptAll = async (): Promise<void> => {
    for (const change of proposed) {
      if (!(await write(change, "apply"))) break;
    }
    refresh();
  };

  if (proposed.length === 0 && applied.length === 0) return null;

  const row = (change: FileChange) => (
    <ChangeRow
      key={change.id}
      change={change}
      busy={busyIds.has(change.id)}
      error={errors[change.id] ?? null}
      onAccept={() => {
        void write(change, "apply").then(refresh);
      }}
      onReject={() => {
        void reject(change).then(refresh);
      }}
      onRevert={() => {
        void write(change, "revert").then(refresh);
      }}
    />
  );

  return (
    <>
      <section
        aria-label={t("changes.title")}
        className="mb-3 flex animate-rise-in flex-wrap items-center justify-between gap-2 rounded-lg border border-rule bg-paper-2 p-3"
      >
        <p className="text-sm text-ink">
          {proposed.length > 0
            ? t("changes.waiting", { count: proposed.length })
            : t("changes.applied", { count: applied.length })}
        </p>
        <Button
          variant={proposed.length > 0 ? "primary" : "ghost"}
          onClick={() => {
            setOpen(true);
          }}
        >
          {t("changes.review")}
        </Button>
      </section>
      <Modal
        open={open}
        size="wide"
        title={t("changes.title")}
        onClose={() => {
          setOpen(false);
        }}
      >
        {root !== null && (
          <p className="mb-3 break-all text-xs text-neutral">{t("changes.folder", { path: root })}</p>
        )}
        {proposed.length > 0 && (
          <div className="mb-2 flex items-center justify-between gap-2">
            <h3 className="text-sm font-medium text-ink">
              {t("changes.waiting", { count: proposed.length })}
            </h3>
            <Button
              variant="primary"
              disabled={busyIds.size > 0}
              onClick={() => {
                void acceptAll();
              }}
            >
              {t("changes.acceptAll")}
            </Button>
          </div>
        )}
        <ul>{proposed.map(row)}</ul>
        {applied.length > 0 && (
          <>
            <h3 className="mb-1 mt-4 text-sm font-medium text-ink">
              {t("changes.applied", { count: applied.length })}
            </h3>
            <ul>{applied.map(row)}</ul>
          </>
        )}
      </Modal>
    </>
  );
}
