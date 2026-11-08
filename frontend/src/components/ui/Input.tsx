import type { InputHTMLAttributes } from "react";
import { cx } from "../../lib/cx";

/** Champ de texte standard de l'application. */
export function Input({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cx(
        "h-9 w-full rounded-md border border-rule bg-paper px-2.5 text-sm text-ink outline-none",
        "placeholder:text-neutral focus:border-rule-strong",
        className,
      )}
      {...rest}
    />
  );
}
