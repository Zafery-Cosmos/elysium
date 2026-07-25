import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cx } from "../../lib/cx";
import { Spinner } from "./Spinner";

type Variant = "primary" | "ghost" | "danger";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  loading?: boolean;
  children: ReactNode;
}

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-accent text-paper font-medium hover:bg-accent/90 active:translate-y-px disabled:bg-paper-3 disabled:text-neutral",
  ghost:
    "border border-rule text-ink hover:border-rule-strong hover:bg-paper-2 active:translate-y-px disabled:text-neutral disabled:hover:bg-transparent",
  danger:
    "border border-danger/40 text-danger hover:bg-danger/10 active:translate-y-px disabled:text-neutral disabled:border-rule",
};

export function Button({
  variant = "ghost",
  loading = false,
  disabled,
  className,
  children,
  type,
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type ?? "button"}
      disabled={disabled === true || loading}
      aria-busy={loading || undefined}
      className={cx(
        "inline-flex h-8 items-center justify-center gap-2 rounded-md px-3 text-sm",
        "transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)]",
        "disabled:cursor-not-allowed",
        VARIANTS[variant],
        className,
      )}
      {...rest}
    >
      {loading && <Spinner className="size-3.5 text-current" />}
      {children}
    </button>
  );
}
