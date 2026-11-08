import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useT } from "../../i18n";
import { useUiStore } from "../../stores/ui";
import { usePrefersReducedMotion } from "../../lib/motion";
import { cx } from "../../lib/cx";
import { Button } from "../ui/Button";
import { IconCheck } from "../layout/icons";
import { TOUR_STEPS } from "./tourSteps";

const FOCUSABLE =
  'a[href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), button:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Tutoriel interactif affiché une fois après la connexion (et rejouable depuis
 * Réglages › Général). Il manipule de FAUX éléments : aucune requête au moteur,
 * aucun fichier écrit. Échap ou « Passer » le ferme, les flèches changent d'étape.
 */
export function OnboardingTour() {
  const t = useT();
  const completeTour = useUiStore((s) => s.completeTour);
  const reduced = usePrefersReducedMotion();
  const [index, setIndex] = useState(0);
  const [tried, setTried] = useState<ReadonlySet<number>>(new Set());
  const panelRef = useRef<HTMLDivElement>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);

  const total = TOUR_STEPS.length;
  const step = TOUR_STEPS[index] ?? TOUR_STEPS[0];
  const last = index === total - 1;

  const next = useCallback((): void => {
    if (index >= total - 1) completeTour();
    else setIndex(index + 1);
  }, [index, total, completeTour]);
  const prev = useCallback((): void => {
    setIndex((i) => Math.max(0, i - 1));
  }, []);

  // Clavier : Échap ferme, flèches naviguent, Tab reste dans la fenêtre.
  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === "Escape") {
        completeTour();
        return;
      }
      if (e.key === "ArrowRight" && !(e.target instanceof HTMLInputElement)) {
        next();
        return;
      }
      if (e.key === "ArrowLeft" && !(e.target instanceof HTMLInputElement)) {
        prev();
        return;
      }
      if (e.key !== "Tab") return;
      const items = panelRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE);
      if (items === undefined || items.length === 0) return;
      const first = items[0];
      const lastItem = items[items.length - 1];
      if (first === undefined || lastItem === undefined) return;
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        lastItem.focus();
      } else if (!e.shiftKey && document.activeElement === lastItem) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, [completeTour, next, prev]);

  // À chaque étape, le titre prend le focus : il est lu par les lecteurs d'écran.
  useEffect(() => {
    titleRef.current?.focus();
  }, [index]);

  const markTried = useCallback((): void => {
    setTried((s) => (s.has(index) ? s : new Set(s).add(index)));
  }, [index]);

  if (step === undefined) return null;
  const Stage = step.Stage;
  const isTried = tried.has(index);

  return createPortal(
    <div className="fixed inset-0 z-[60] flex items-start justify-center overflow-y-auto bg-ink/40 px-4 py-[5vh]">
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={t("tour.dialog")}
        className="w-full max-w-4xl animate-rise-in rounded-lg border border-rule bg-paper p-5 shadow-lg shadow-ink/10 sm:p-6"
      >
        <div className="flex items-center justify-between gap-3">
          <p className="text-xs text-neutral" aria-live="polite">
            {t("tour.step", { n: index + 1, total })}
          </p>
          <button
            type="button"
            onClick={completeTour}
            className="h-8 rounded-md px-2 text-xs text-muted underline-offset-4 hover:text-ink hover:underline"
          >
            {t("tour.skip")}
          </button>
        </div>

        <div className="mt-3 grid gap-5 md:grid-cols-[2fr_3fr]">
          <div key={step.id} className="animate-fade-in">
            <h2
              ref={titleRef}
              tabIndex={-1}
              className="text-xl text-ink outline-none"
            >
              {t(step.title)}
            </h2>
            <p className="mt-2 text-sm leading-relaxed text-muted">{t(step.body)}</p>
            {step.id === "team" && (
              <ul className="mt-4 flex flex-col gap-1.5 text-sm text-ink">
                {(["tour.s0.b1", "tour.s0.b2", "tour.s0.b3"] as const).map((key) => (
                  <li key={key} className="flex items-center gap-2">
                    <IconCheck width={13} height={13} aria-hidden="true" className="shrink-0" />
                    {t(key)}
                  </li>
                ))}
              </ul>
            )}
            {step.action !== undefined && (
              <p
                className={cx(
                  "mt-4 rounded-md border px-3 py-2 text-sm",
                  isTried ? "border-ink text-ink" : "border-rule text-muted",
                )}
                role="status"
              >
                <span className="font-medium text-ink">{isTried ? t("tour.tryDone") : t("tour.try")}</span>{" "}
                {isTried ? "" : t(step.action)}
              </p>
            )}
          </div>

          <div className="min-w-0 rounded-lg border border-rule bg-paper-2 p-3 sm:p-4">
            <p className="mb-3 text-xs text-neutral">{t("tour.demo")}</p>
            <Stage key={step.id} reduced={reduced} onDone={markTried} />
          </div>
        </div>

        <div className="mt-5 flex items-center justify-between gap-3">
          <div className="flex items-center gap-1.5" aria-hidden="true">
            {TOUR_STEPS.map((s, i) => (
              <span
                key={s.id}
                className={cx(
                  "h-1.5 rounded-full transition-all duration-[var(--dur-base)] ease-[var(--ease-out)]",
                  i === index ? "w-5 bg-ink" : i < index ? "w-1.5 bg-ink/60" : "w-1.5 bg-rule-strong",
                )}
              />
            ))}
          </div>
          <div className="flex items-center gap-2">
            <Button onClick={prev} disabled={index === 0}>
              {t("tour.prev")}
            </Button>
            <Button variant="primary" onClick={next}>
              {last ? t("tour.done") : t("tour.next")}
            </Button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
