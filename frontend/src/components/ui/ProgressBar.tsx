/** Barre de progression sobre. `value` en 0–1. */
export function ProgressBar({
  value,
  label,
}: {
  value: number;
  label?: string;
}) {
  const pct = Math.round(Math.min(1, Math.max(0, value)) * 100);
  return (
    <div
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={pct}
      aria-label={label}
      className="h-1 w-full overflow-hidden rounded-full bg-[#eeeeee]"
    >
      <div
        className="h-full rounded-full bg-ink transition-[width] duration-[var(--dur-base)] ease-[var(--ease-out)]"
        style={{ width: `${String(pct)}%` }}
      />
    </div>
  );
}
