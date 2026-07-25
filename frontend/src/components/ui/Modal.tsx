import { useEffect, useRef, type ReactNode } from "react";

/**
 * Boîte de dialogue modale minimaliste : Échap ferme, clic sur le fond
 * ferme, le focus entre dans la boîte à l'ouverture.
 */
export function Modal({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    // Focus sur le premier champ ou bouton de la boîte.
    const panel = panelRef.current;
    const focusable = panel?.querySelector<HTMLElement>(
      "input, textarea, select, button",
    );
    focusable?.focus();
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-paper/80 px-4 pt-[15vh]"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="w-full max-w-md animate-fade-in rounded-lg border border-rule bg-paper-2 p-6 shadow-2xl shadow-paper/60"
      >
        <h2 className="mb-4 text-md">{title}</h2>
        {children}
      </div>
    </div>
  );
}
