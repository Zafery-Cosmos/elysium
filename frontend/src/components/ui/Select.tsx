import { useId, type SelectHTMLAttributes } from "react";
import { cx } from "../../lib/cx";
import { IconChevronDown } from "../layout/icons";

export interface SelectOption {
  value: string;
  label: string;
}

/** Liste déroulante native stylée, monochrome, avec libellé optionnel. */
export function Select({
  label,
  options,
  className,
  ...rest
}: {
  label?: string;
  options: SelectOption[];
} & SelectHTMLAttributes<HTMLSelectElement>) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1.5">
      {label !== undefined && (
        <label htmlFor={id} className="text-sm font-medium text-muted">
          {label}
        </label>
      )}
      <div className="relative">
        <select
          id={id}
          className={cx(
            "w-full appearance-none rounded-md border border-rule bg-paper py-2 pr-9 pl-3 text-sm text-ink",
            "transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)] hover:border-rule-strong",
            "disabled:cursor-not-allowed disabled:opacity-60",
            className,
          )}
          {...rest}
        >
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <IconChevronDown
          width={14}
          height={14}
          className="pointer-events-none absolute top-1/2 right-3 -translate-y-1/2 text-neutral"
        />
      </div>
    </div>
  );
}
