import { useT } from "../../i18n";
import { Button } from "../ui/Button";

/**
 * Validation d'un plan fraîchement généré (même logique que le mode Plan de
 * Claude Code : on propose, l'utilisateur valide ou refuse AVANT toute suite).
 *
 * - Valider : l'équipe analyse chaque tâche du plan (Expert › Analyse, lecture
 *   seule : aucun fichier n'est modifié).
 * - Refuser : les tâches non commencées du plan sont retirées du tableau.
 * - Modifier : décrire le changement en mode Plan ; le nouveau plan REMPLACE
 *   l'ancien (pas de doublon).
 */
export function PlanApproval({
  count,
  busy,
  onApprove,
  onReject,
}: {
  count: number;
  busy: boolean;
  onApprove: () => void;
  onReject: () => void;
}) {
  const t = useT();
  return (
    <section
      aria-label={t("chat.plan.title")}
      className="mb-3 animate-rise-in rounded-lg border border-rule bg-paper-2 p-4"
    >
      <p className="text-sm font-medium text-ink">{t("chat.plan.ready", { count })}</p>
      <p className="mt-1 text-xs text-neutral">{t("chat.plan.hint")}</p>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button variant="primary" onClick={onApprove} disabled={busy}>
          {t("chat.plan.approve")}
        </Button>
        <Button variant="ghost" onClick={onReject} disabled={busy}>
          {t("chat.plan.reject")}
        </Button>
      </div>
    </section>
  );
}
