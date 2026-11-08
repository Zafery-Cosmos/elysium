import { useState } from "react";
import { engine, toHumanMessage } from "../../services/engine";
import { isTauri, pickDirectory } from "../../services/endpoint";
import { useT } from "../../i18n";
import { Button } from "../ui/Button";
import { Input } from "../ui/Input";

/** Le mode Complet a besoin d'un dossier : on le relie ici, sans changer de page. */
export function WorkspaceLink({
  projectId,
  onLinked,
}: {
  projectId: string;
  onLinked: () => void;
}) {
  const t = useT();
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const link = async (folder: string): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      await engine.scanMemory(projectId, folder);
      onLinked();
    } catch (err) {
      setError(toHumanMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const choose = async (): Promise<void> => {
    const picked = await pickDirectory();
    if (picked !== null) await link(picked);
  };

  return (
    <section
      aria-label={t("workspace.title")}
      className="mb-3 animate-rise-in rounded-lg border border-rule bg-paper-2 p-4"
    >
      <p className="text-sm font-medium text-ink">{t("workspace.title")}</p>
      <p className="mt-1 text-xs text-neutral">{t("workspace.hint")}</p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {isTauri() ? (
          <Button
            variant="primary"
            disabled={busy}
            onClick={() => {
              void choose();
            }}
          >
            {t("workspace.choose")}
          </Button>
        ) : (
          <>
            <Input
              aria-label={t("preview.path.placeholder")}
              placeholder={t("preview.path.placeholder")}
              value={path}
              onChange={(e) => {
                setPath(e.target.value);
              }}
            />
            <Button
              variant="primary"
              disabled={busy || path.trim().length === 0}
              onClick={() => {
                void link(path.trim());
              }}
            >
              {t("workspace.link")}
            </Button>
          </>
        )}
      </div>
      {error !== null && (
        <p role="alert" className="mt-2 text-xs text-danger">
          {error}
        </p>
      )}
    </section>
  );
}
