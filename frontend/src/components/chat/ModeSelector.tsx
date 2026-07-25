import { CHAT_MODES } from "../../lib/labels";
import { cx } from "../../lib/cx";
import type { ChatMode } from "../../types/engine";

/**
 * Sélecteur de mode de conversation : trois puces au-dessus de la saisie.
 * Puce noire quand actif, contour sinon ; l'infobulle décrit chaque mode.
 */
export function ModeSelector({
  value,
  onChange,
  disabled = false,
}: {
  value: ChatMode;
  onChange: (mode: ChatMode) => void;
  disabled?: boolean;
}) {
  return (
    <div
      role="radiogroup"
      aria-label="Mode de conversation"
      className="flex items-center gap-1.5"
    >
      {CHAT_MODES.map((mode) => {
        const selected = value === mode.value;
        return (
          <button
            key={mode.value}
            type="button"
            role="radio"
            aria-checked={selected}
            title={mode.hint}
            disabled={disabled}
            onClick={() => {
              onChange(mode.value);
            }}
            className={cx(
              "h-7 rounded-full border px-3 text-xs",
              "transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)]",
              "disabled:cursor-not-allowed disabled:opacity-60",
              selected
                ? "border-ink bg-ink font-medium text-paper"
                : "border-rule bg-paper text-muted hover:border-rule-strong hover:text-ink",
            )}
          >
            {mode.label}
          </button>
        );
      })}
    </div>
  );
}
