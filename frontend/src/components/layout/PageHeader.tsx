import type { ReactNode } from "react";

/** En-tête de page : titre + action à droite, hauteur fixe et sobre. */
export function PageHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
}) {
  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-4 border-b border-rule px-6">
      <div className="flex min-w-0 items-baseline gap-3">
        <h1 className="truncate text-md">{title}</h1>
        {subtitle !== undefined && (
          <p className="hidden truncate text-sm text-neutral sm:block">
            {subtitle}
          </p>
        )}
      </div>
      {action !== undefined && <div className="shrink-0">{action}</div>}
    </header>
  );
}
