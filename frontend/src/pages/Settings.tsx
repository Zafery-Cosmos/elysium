import { useEffect, useState } from "react";
import { PageHeader } from "../components/layout/PageHeader";
import { useUiStore, type UiMode } from "../stores/ui";
import { engine } from "../services/engine";
import { isTauri } from "../services/endpoint";
import { cx } from "../lib/cx";
import type { HealthInfo } from "../types/engine";

function ModeToggle() {
  const mode = useUiStore((s) => s.mode);
  const setMode = useUiStore((s) => s.setMode);

  const options: Array<{ value: UiMode; label: string; hint: string }> = [
    {
      value: "simple",
      label: "Simple",
      hint: "L'essentiel, sans jargon technique.",
    },
    {
      value: "advanced",
      label: "Avancé",
      hint: "Modèles, événements bruts et détails techniques visibles.",
    },
  ];

  return (
    <div
      role="radiogroup"
      aria-label="Mode d'affichage"
      className="flex flex-col gap-2 sm:flex-row"
    >
      {options.map((option) => {
        const selected = mode === option.value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => {
              setMode(option.value);
            }}
            className={cx(
              "flex flex-1 flex-col items-start gap-1 rounded-lg border px-4 py-3 text-left",
              "transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)]",
              selected
                ? "border-accent-dim bg-paper-2"
                : "border-rule hover:border-rule-strong hover:bg-paper-2/50",
            )}
          >
            <span
              className={cx(
                "text-sm font-medium",
                selected ? "text-accent" : "text-ink",
              )}
            >
              {option.label}
            </span>
            <span className="text-xs text-neutral">{option.hint}</span>
          </button>
        );
      })}
    </div>
  );
}

export function Settings() {
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [healthError, setHealthError] = useState(false);
  const mode = useUiStore((s) => s.mode);

  useEffect(() => {
    let cancelled = false;
    engine
      .health()
      .then((info) => {
        if (!cancelled) setHealth(info);
      })
      .catch(() => {
        if (!cancelled) setHealthError(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <PageHeader title="Réglages" />
      <div className="flex max-w-2xl flex-col gap-10 p-6">
        <section aria-label="Mode d'affichage" className="flex flex-col gap-3">
          <h2 className="text-sm font-medium text-muted">Mode d'affichage</h2>
          <ModeToggle />
        </section>

        <section aria-label="Apparence" className="flex flex-col gap-3">
          <h2 className="text-sm font-medium text-muted">Apparence</h2>
          <p className="text-sm text-neutral">
            Elysium utilise pour l'instant un thème sombre unique, pensé pour
            les longues sessions. Un thème clair est prévu.
          </p>
        </section>

        <section aria-label="À propos" className="flex flex-col gap-3">
          <h2 className="text-sm font-medium text-muted">À propos</h2>
          <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
            <dt className="text-neutral">Application</dt>
            <dd className="text-ink">
              Elysium — environnement de développement IA open source
            </dd>
            <dt className="text-neutral">Contexte</dt>
            <dd className="text-ink">
              {isTauri() ? "Application de bureau (Tauri)" : "Navigateur (dev)"}
            </dd>
            <dt className="text-neutral">Moteur IA</dt>
            <dd className="text-ink">
              {healthError
                ? "Injoignable — vérifiez qu'Elysium est bien démarré."
                : health === null
                  ? "Vérification…"
                  : `En ligne${
                      mode === "advanced" && health.version !== undefined
                        ? ` · v${health.version}`
                        : ""
                    }`}
            </dd>
          </dl>
        </section>
      </div>
    </div>
  );
}
