import { useId, type SelectHTMLAttributes } from "react";
import { cx } from "../../lib/cx";
import { IconChevronDown } from "../layout/icons";

export interface SelectOption {
  value: string;
  label: string;
  /** Regroupe les options consécutives de même groupe dans un <optgroup>. */
  group?: string;
}

/** Découpe les options en segments consécutifs : sans groupe, ou sous un même libellé de groupe. */
function segments(options: SelectOption[]): Array<{ group?: string; items: SelectOption[] }> {
  const out: Array<{ group?: string; items: SelectOption[] }> = [];
  for (const option of options) {
    const last = out[out.length - 1];
    if (last !== undefined && last.group === option.group) last.items.push(option);
    else out.push({ group: option.group, items: [option] });
  }
  return out;
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
          {segments(options).map((segment, index) => {
            const items = segment.items.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ));
            return segment.group === undefined ? (
              items
            ) : (
              <optgroup key={`${segment.group}-${String(index)}`} label={segment.group}>
                {items}
              </optgroup>
            );
          })}
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
