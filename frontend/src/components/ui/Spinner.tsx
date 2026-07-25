import { cx } from "../../lib/cx";

export function Spinner({ className }: { className?: string }) {
  return (
    <svg
      className={cx("size-4 animate-spin text-neutral", className)}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <circle
        cx="12"
        cy="12"
        r="9"
        stroke="currentColor"
        strokeWidth="2"
        opacity="0.25"
      />
      <path
        d="M21 12a9 9 0 0 0-9-9"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function LoadingBlock({ label }: { label: string }) {
  return (
    <div
      className="flex items-center gap-3 px-6 py-16 text-sm text-neutral"
      role="status"
    >
      <Spinner />
      <span>{label}</span>
    </div>
  );
}
