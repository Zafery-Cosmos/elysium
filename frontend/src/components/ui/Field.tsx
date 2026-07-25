import { useId, type InputHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { cx } from "../../lib/cx";

const INPUT_CLASS = cx(
  "w-full rounded-md border border-rule bg-paper px-3 py-2 text-sm text-ink",
  "placeholder:text-neutral",
  "transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)]",
  "hover:border-rule-strong",
  "disabled:cursor-not-allowed disabled:opacity-60",
  "aria-[invalid=true]:border-danger",
);

interface FieldBaseProps {
  label: string;
  hint?: string;
}

export function TextField({
  label,
  hint,
  className,
  ...rest
}: FieldBaseProps & InputHTMLAttributes<HTMLInputElement>) {
  const id = useId();
  const hintId = `${id}-hint`;
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium text-muted">
        {label}
      </label>
      <input
        id={id}
        aria-describedby={hint !== undefined ? hintId : undefined}
        className={cx(INPUT_CLASS, className)}
        {...rest}
      />
      {hint !== undefined && (
        <p id={hintId} className="text-xs text-neutral">
          {hint}
        </p>
      )}
    </div>
  );
}

export function TextAreaField({
  label,
  hint,
  className,
  ...rest
}: FieldBaseProps & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const id = useId();
  const hintId = `${id}-hint`;
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium text-muted">
        {label}
      </label>
      <textarea
        id={id}
        aria-describedby={hint !== undefined ? hintId : undefined}
        className={cx(INPUT_CLASS, "min-h-20 resize-y", className)}
        {...rest}
      />
      {hint !== undefined && (
        <p id={hintId} className="text-xs text-neutral">
          {hint}
        </p>
      )}
    </div>
  );
}
