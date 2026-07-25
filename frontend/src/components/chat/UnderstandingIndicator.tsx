import { ProgressBar } from "../ui/ProgressBar";

/**
 * Compréhension du projet — heuristique de couverture alimentée par les
 * événements agent_status / decision (cf. ADR-005 : ce n'est pas une
 * probabilité du modèle).
 */
export function UnderstandingIndicator({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  return (
    <div className="flex items-center gap-3 border-b border-rule px-6 py-2.5">
      <span className="shrink-0 text-xs text-neutral">
        Compréhension du projet
      </span>
      <div className="max-w-56 flex-1">
        <ProgressBar value={value} label="Compréhension du projet" />
      </div>
      <span className="shrink-0 font-mono text-xs text-muted">
        {pct} %
      </span>
    </div>
  );
}
