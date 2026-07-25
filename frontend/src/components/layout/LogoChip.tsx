import { cx } from "../../lib/cx";

/**
 * Le logo a des traits clairs : sur fond blanc il disparaît. Il est donc
 * toujours posé sur une pastille noire pure (carré arrondi ou cercle).
 */
export function LogoChip({ className }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cx(
        // Fond toujours noir (le logo a des traits clairs) + liseré qui la
        // détache aussi bien sur fond blanc que sur fond sombre.
        "grid shrink-0 place-items-center overflow-hidden border border-rule bg-chip",
        className ?? "size-7 rounded-md p-0.5",
      )}
    >
      <img
        src="/logo.png"
        alt=""
        className="size-full select-none object-contain"
        draggable={false}
      />
    </span>
  );
}
