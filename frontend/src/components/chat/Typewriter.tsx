import { useEffect, useRef, useState } from "react";
import { usePrefersReducedMotion } from "../../lib/motion";
import { cx } from "../../lib/cx";

const TYPE_MS = 45;
const DELETE_MS = 25;
const HOLD_MS = 1500;
/** Mouvement réduit : simple rotation, sans frappe caractère par caractère. */
const STATIC_ROTATE_MS = 3200;

/**
 * Effet « machine à écrire » : tape un exemple, marque une pause, l'efface,
 * puis passe au suivant. Respecte le mouvement réduit (rotation simple, sans
 * animation par caractère). Les minuteries sont nettoyées au démontage.
 */
export function Typewriter({
  phrases,
  className,
}: {
  phrases: string[];
  className?: string;
}) {
  const reduced = usePrefersReducedMotion();
  const [index, setIndex] = useState(0);
  const [text, setText] = useState(reduced ? (phrases[0] ?? "") : "");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Mode réduit : rotation d'exemples complets, sans frappe.
  useEffect(() => {
    if (!reduced || phrases.length <= 1) return;
    const id = setInterval(() => {
      setIndex((i) => (i + 1) % phrases.length);
    }, STATIC_ROTATE_MS);
    return () => {
      clearInterval(id);
    };
  }, [reduced, phrases.length]);

  useEffect(() => {
    if (reduced) {
      setText(phrases[index] ?? "");
    }
  }, [reduced, index, phrases]);

  // Mode animé : frappe / effacement caractère par caractère.
  useEffect(() => {
    if (reduced || phrases.length === 0) return;
    const full = phrases[index] ?? "";
    let len = 0;
    let deleting = false;

    const tick = (): void => {
      len = deleting ? len - 1 : len + 1;
      len = Math.max(0, Math.min(full.length, len));
      setText(full.slice(0, len));

      if (!deleting && len === full.length) {
        deleting = true;
        timer.current = setTimeout(tick, HOLD_MS);
        return;
      }
      if (deleting && len === 0) {
        setIndex((i) => (i + 1) % phrases.length);
        return;
      }
      timer.current = setTimeout(tick, deleting ? DELETE_MS : TYPE_MS);
    };

    setText("");
    timer.current = setTimeout(tick, TYPE_MS);
    return () => {
      if (timer.current !== null) clearTimeout(timer.current);
    };
  }, [index, reduced, phrases]);

  return (
    <p
      className={cx("text-sm text-muted", className)}
      aria-live="off"
    >
      <span className="text-neutral">par ex. </span>
      <span className="text-ink">{text}</span>
      {!reduced && (
        <span
          aria-hidden="true"
          className="ml-0.5 inline-block h-4 w-px translate-y-0.5 animate-caret-blink bg-ink align-baseline"
        />
      )}
    </p>
  );
}
