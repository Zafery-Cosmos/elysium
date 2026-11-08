import { useT } from "../../i18n";
import { Button } from "../ui/Button";
import type { PendingAction } from "../../types/engine";

/** Un agent demande un outil MCP : rien ne s'exécute sans décision explicite. */
export function ActionApproval({
  action,
  onDecide,
}: {
  action: PendingAction;
  onDecide: (approved: boolean) => void;
}) {
  const t = useT();
  return (
    <section
      aria-label={t("action.title")}
      className="mb-3 animate-rise-in rounded-lg border border-rule bg-paper-2 p-4"
    >
      <p className="text-sm font-medium text-ink">
        {t("action.request", { agent: action.agent, tool: action.tool, server: action.server })}
      </p>
      <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-md border border-rule bg-paper p-2 font-mono text-xs text-muted">
        {action.arguments}
      </pre>
      <p className="mt-2 text-xs text-neutral">{t("action.hint")}</p>
      <div className="mt-3 flex flex-wrap gap-2">
        {/* Refuser en premier : valider n'est jamais l'action par défaut. */}
        <Button
          variant="ghost"
          onClick={() => {
            onDecide(false);
          }}
        >
          {t("action.deny")}
        </Button>
        <Button
          variant="primary"
          onClick={() => {
            onDecide(true);
          }}
        >
          {t("action.allow")}
        </Button>
      </div>
    </section>
  );
}
