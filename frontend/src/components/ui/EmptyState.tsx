import type { ReactNode } from "react";

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-start gap-2 rounded-lg border border-dashed border-rule px-6 py-10">
      <p className="text-sm font-medium text-muted">{title}</p>
      {description !== undefined && (
        <p className="max-w-prose text-sm text-neutral">{description}</p>
      )}
      {action !== undefined && <div className="mt-2">{action}</div>}
    </div>
  );
}
