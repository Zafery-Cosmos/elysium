import { CHAT_EXECUTIONS } from "../../lib/labels";
import { SelectPill } from "./SelectPill";
import type { Execution } from "../../types/engine";

/**
 * Sélecteur du mode d'exécution (Simple / Expert), en pastille compacte
 * (cf. SelectPill) : montre l'exécution courante + un chevron, ouvre un
 * petit panneau de choix décrivant chaque option.
 */
export function ExecutionSelector({
  value,
  onChange,
  disabled = false,
  placement = "top",
}: {
  value: Execution;
  onChange: (execution: Execution) => void;
  disabled?: boolean;
  placement?: "top" | "bottom";
}) {
  return (
    <SelectPill
      ariaLabel="Mode d'exécution"
      title="Mode d'exécution"
      value={value}
      options={CHAT_EXECUTIONS}
      onChange={onChange}
      disabled={disabled}
      placement={placement}
    />
  );
}
