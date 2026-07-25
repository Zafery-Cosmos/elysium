import { CHAT_EXECUTIONS } from "../../lib/labels";
import { cx } from "../../lib/cx";
import type { Execution } from "../../types/engine";

/**
 * Sélecteur du mode d'exécution : Simple (un modèle solo) ou Expert (l'équipe
 * d'agents collabore). Même principe visuel que le sélecteur de mode : puce
 * noire quand actif, contour sinon.
 */
export function ExecutionSelector({
  value,
  onChange,
  disabled = false,
}: {
  value: Execution;
  onChange: (execution: Execution) => void;
  disabled?: boolean;
}) {
  return (
    <div
      role="radiogroup"
      aria-label="Mode d'exécution"
      className="flex items-center gap-1.5"
    >
      {CHAT_EXECUTIONS.map((exec) => {
        const selected = value === exec.value;
        return (
          <button
            key={exec.value}
            type="button"
            role="radio"
            aria-checked={selected}
            title={exec.hint}
            disabled={disabled}
            onClick={() => {
              onChange(exec.value);
            }}
            className={cx(
              "h-7 rounded-full border px-3 text-xs",
              "transition-[color,background-color,border-color,transform] duration-[var(--dur-fast)] ease-[var(--ease-out)]",
              "active:scale-95 disabled:cursor-not-allowed disabled:opacity-60",
              selected
                ? "border-ink bg-ink font-medium text-paper"
                : "border-rule bg-paper text-muted hover:border-rule-strong hover:text-ink",
            )}
          >
            {exec.label}
          </button>
        );
      })}
    </div>
  );
}
