import { cx } from "../../lib/cx";

/** Interrupteur monochrome accessible : noir quand actif. */
export function Toggle({
  checked,
  onChange,
  label,
  disabled = false,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  /** Libellé accessible (aria-label). */
  label: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => {
        onChange(!checked);
      }}
      className={cx(
        "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border",
        "transition-colors duration-[var(--dur-base)] ease-[var(--ease-out)]",
        "disabled:cursor-not-allowed disabled:opacity-50",
        checked ? "border-ink bg-ink" : "border-rule-strong bg-paper-3",
      )}
    >
      <span
        aria-hidden="true"
        className={cx(
          "inline-block size-3.5 rounded-full bg-paper shadow-sm",
          "transition-transform duration-[var(--dur-base)] ease-[var(--ease-out)]",
          checked ? "translate-x-[18px]" : "translate-x-0.5",
        )}
      />
    </button>
  );
}
