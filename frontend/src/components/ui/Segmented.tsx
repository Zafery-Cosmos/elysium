import { cx } from "../../lib/cx";

export interface SegmentOption<T extends string> {
  value: T;
  label: string;
  hint?: string;
}

/** Contrôle segmenté monochrome (radiogroup) : segment noir quand actif. */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  label,
  disabled = false,
}: {
  options: Array<SegmentOption<T>>;
  value: T;
  onChange: (value: T) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className="inline-flex flex-wrap gap-1 rounded-lg border border-rule bg-paper-2 p-1"
    >
      {options.map((option) => {
        const selected = value === option.value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            title={option.hint}
            disabled={disabled}
            onClick={() => {
              onChange(option.value);
            }}
            className={cx(
              "h-7 rounded-md px-3 text-xs",
              "transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)]",
              "disabled:cursor-not-allowed disabled:opacity-60",
              selected
                ? "bg-ink font-medium text-paper"
                : "text-muted hover:text-ink",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
