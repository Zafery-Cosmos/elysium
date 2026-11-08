import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

const FOCUSABLE =
  'a[href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), button:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Boîte de dialogue modale : Échap ferme, clic sur le fond ferme, le focus
 * entre une seule fois à l'ouverture, reste dans la boîte et revient ensuite
 * à l'élément qui l'avait ouverte.
 */
export function Modal({
  open,
  title,
  onClose,
  children,
  size = "normal",
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  /** `wide` : contenus larges (diff, tableau). */
  size?: "normal" | "wide";
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  // `onClose` change souvent d'identité : le focus ne doit pas en dépendre,
  // sinon chaque frappe dans un formulaire le renvoie au premier champ.
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === "Escape") {
        onCloseRef.current();
        return;
      }
      if (e.key !== "Tab") return;
      const items = panelRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE);
      if (items === undefined || items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (first === undefined || last === undefined) return;
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    panelRef.current?.querySelector<HTMLElement>("input, textarea, select, button")?.focus();
    return () => {
      document.removeEventListener("keydown", onKey);
      previous?.focus();
    };
  }, [open]);

  if (!open) return null;

  // Rendu dans <body> : une page animée (transform) devient le bloc conteneur
  // des éléments `fixed` qu'elle contient, et la boîte s'affichait alors à
  // l'intérieur de la carte (fond gris partiel, boîte coupée par la liste).
  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink/20 px-4 py-[8vh]"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`w-full ${size === "wide" ? "max-w-5xl" : "max-w-md"} animate-fade-in rounded-lg border border-rule bg-paper p-6 shadow-lg shadow-ink/10`}
      >
        <h2 className="mb-4 text-md">{title}</h2>
        {children}
      </div>
    </div>,
    document.body,
  );
}
