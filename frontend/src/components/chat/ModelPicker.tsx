import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { Link } from "react-router-dom";
import { useModelsStore } from "../../stores/models";
import { EFFORT_LEVELS, providerMeta } from "../../lib/labels";
import {
  costTierLabel,
  formatContextWindow,
  releaseYear,
} from "../../lib/format";
import { cx } from "../../lib/cx";
import { IconCheck } from "../layout/icons";
import type { Effort, ModelInfo, ProviderInfo } from "../../types/engine";

function modelValue(provider: ProviderInfo, model: ModelInfo): string | null {
  const id = model.id ?? model.name;
  if (id === undefined || id.length === 0) return null;
  return `${provider.name}:${id}`;
}

function modelLabel(model: ModelInfo): string {
  return model.display_name ?? model.name ?? model.id ?? "Modèle";
}

/** Ligne secondaire « 2025 · 200K contexte ». */
function modelMeta(model: ModelInfo): string | null {
  const parts: string[] = [];
  const year = releaseYear(model.release_date);
  if (year !== null) parts.push(year);
  const context = formatContextWindow(model.context_window);
  if (context !== null) parts.push(`${context} contexte`);
  return parts.length > 0 ? parts.join(" · ") : null;
}

function ModelRow({
  provider,
  model,
  selected,
  onSelect,
}: {
  provider: ProviderInfo;
  model: ModelInfo;
  selected: boolean;
  onSelect: (value: string) => void;
}) {
  const value = modelValue(provider, model);
  const configured = provider.configured === true;
  const meta = modelMeta(model);
  const cost = costTierLabel(model.cost_tier);
  if (value === null) return null;
  return (
    <button
      type="button"
      data-option
      disabled={!configured}
      aria-pressed={selected}
      onClick={() => {
        onSelect(value);
      }}
      className={cx(
        "flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left",
        "transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)]",
        configured
          ? "hover:bg-paper-3"
          : "cursor-not-allowed opacity-50",
        selected && "bg-paper-3",
      )}
    >
      <span className="min-w-0 flex-1">
        <span
          className={cx(
            "block truncate text-sm",
            selected ? "font-medium text-ink" : "text-ink",
          )}
        >
          {modelLabel(model)}
        </span>
        {meta !== null && (
          <span className="block truncate text-xs text-neutral">{meta}</span>
        )}
      </span>
      {cost !== null && (
        <span
          aria-label={`Coût : ${cost} sur $$$$`}
          className={cx(
            "shrink-0 font-mono text-xs",
            selected ? "text-ink" : "text-neutral",
          )}
        >
          {cost}
        </span>
      )}
      {selected && (
        <IconCheck width={13} height={13} className="shrink-0 text-ink" />
      )}
    </button>
  );
}

/**
 * Pastille compacte « ● modèle » ouvrant un panneau : modèles groupés
 * par fournisseur (GET /models) + réglage d'effort. Échap ferme, flèches
 * naviguent, clic à l'extérieur ferme.
 */
export function ModelPicker({
  model,
  effort,
  onModelChange,
  onEffortChange,
}: {
  model: string | null;
  effort: Effort;
  onModelChange: (model: string | null) => void;
  onEffortChange: (effort: Effort) => void;
}) {
  const providers = useModelsStore((s) => s.providers);
  const status = useModelsStore((s) => s.status);
  const fetch = useModelsStore((s) => s.fetch);
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (status === "idle") void fetch();
  }, [status, fetch]);

  // Fermeture : Échap (avec retour du focus) et clic à l'extérieur.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: globalThis.KeyboardEvent): void => {
      if (e.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    const onPointerDown = (e: PointerEvent): void => {
      if (
        e.target instanceof Node &&
        containerRef.current?.contains(e.target) !== true
      ) {
        setOpen(false);
      }
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointerDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointerDown);
    };
  }, [open]);

  const groups = useMemo(
    () => providers.filter((p) => (p.models?.length ?? 0) > 0),
    [providers],
  );

  const selectedLabel = useMemo(() => {
    if (model === null) return null;
    for (const provider of providers) {
      for (const m of provider.models ?? []) {
        if (modelValue(provider, m) === model) return modelLabel(m);
      }
    }
    // Modèle choisi mais catalogue pas (encore) chargé : partie lisible.
    return model.split(":").slice(1).join(":") || model;
  }, [model, providers]);

  const effortLabel =
    EFFORT_LEVELS.find((l) => l.value === effort)?.label ?? "Moyen";

  // Flèches : navigation entre les modèles sélectionnables du panneau.
  const onPanelKeyDown = (e: KeyboardEvent<HTMLDivElement>): void => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const panel = panelRef.current;
    if (panel === null) return;
    const options = [
      ...panel.querySelectorAll<HTMLButtonElement>(
        "button[data-option]:not(:disabled)",
      ),
    ];
    if (options.length === 0) return;
    e.preventDefault();
    const active = document.activeElement;
    const index = options.findIndex((o) => o === active);
    const delta = e.key === "ArrowDown" ? 1 : -1;
    const next =
      index === -1
        ? 0
        : (index + delta + options.length) % options.length;
    options[next]?.focus();
  };

  return (
    <div ref={containerRef} className="relative">
      <button
        ref={buttonRef}
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        title="Choisir le modèle et l'effort"
        onClick={() => {
          setOpen((v) => !v);
        }}
        className={cx(
          "flex h-7 items-center gap-2 rounded-full border border-rule bg-paper px-3 text-xs",
          "transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)]",
          "hover:border-rule-strong hover:bg-paper-2",
          open && "border-rule-strong bg-paper-2",
        )}
      >
        <span aria-hidden="true" className="size-1.5 rounded-full bg-ink" />
        <span className="max-w-44 truncate text-ink">
          {selectedLabel ?? "Modèle automatique"}
        </span>
        <span className="text-neutral">· {effortLabel}</span>
      </button>

      {open && (
        <div
          ref={panelRef}
          role="dialog"
          aria-label="Choix du modèle et de l'effort"
          onKeyDown={onPanelKeyDown}
          className={cx(
            "absolute right-0 bottom-full z-30 mb-2 w-80 animate-rise-in",
            "rounded-xl border border-rule bg-paper p-2 shadow-lg shadow-ink/10",
          )}
        >
          <div className="max-h-72 overflow-y-auto">
            <button
              type="button"
              data-option
              aria-pressed={model === null}
              onClick={() => {
                onModelChange(null);
                setOpen(false);
                buttonRef.current?.focus();
              }}
              className={cx(
                "flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left",
                "transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)] hover:bg-paper-3",
                model === null && "bg-paper-3",
              )}
            >
              <span className="min-w-0 flex-1">
                <span
                  className={cx(
                    "block text-sm text-ink",
                    model === null && "font-medium",
                  )}
                >
                  Automatique
                </span>
                <span className="block text-xs text-neutral">
                  Le moteur choisit selon la tâche
                </span>
              </span>
              {model === null && (
                <IconCheck
                  width={13}
                  height={13}
                  className="shrink-0 text-ink"
                />
              )}
            </button>

            {groups.map((provider) => {
              const meta = providerMeta(provider.name);
              const configured = provider.configured === true;
              return (
                <div key={provider.name} className="mt-2">
                  <div className="flex items-center justify-between px-2.5 pb-1">
                    <p className="text-xs font-medium text-neutral">
                      {provider.label ?? meta.label}
                    </p>
                    {!configured && (
                      <Link
                        to="/models"
                        className="rounded-sm text-xs text-muted underline-offset-2 hover:text-ink hover:underline"
                      >
                        Configurer →
                      </Link>
                    )}
                  </div>
                  {(provider.models ?? []).map((m, index) => (
                    <ModelRow
                      key={m.id ?? m.name ?? String(index)}
                      provider={provider}
                      model={m}
                      selected={
                        model !== null && modelValue(provider, m) === model
                      }
                      onSelect={(value) => {
                        onModelChange(value);
                        setOpen(false);
                        buttonRef.current?.focus();
                      }}
                    />
                  ))}
                </div>
              );
            })}

            {status === "ready" && groups.length === 0 && (
              <p className="px-2.5 py-3 text-xs text-neutral">
                Aucun modèle disponible.{" "}
                <Link
                  to="/models"
                  className="rounded-sm text-muted underline underline-offset-2 hover:text-ink"
                >
                  Configurer un fournisseur →
                </Link>
              </p>
            )}
            {status === "loading" && (
              <p className="px-2.5 py-3 text-xs text-neutral" role="status">
                Chargement des modèles…
              </p>
            )}
            {status === "error" && (
              <p className="px-2.5 py-3 text-xs text-neutral">
                Modèles indisponibles pour l'instant.
              </p>
            )}
          </div>

          <div className="mt-2 border-t border-rule pt-2">
            <p className="px-2.5 pb-1 text-xs font-medium text-neutral">
              Effort
            </p>
            <div
              role="radiogroup"
              aria-label="Niveau d'effort"
              className="grid grid-cols-3 gap-1 px-1 pb-1"
            >
              {EFFORT_LEVELS.map((level) => {
                const selected = effort === level.value;
                return (
                  <button
                    key={level.value}
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    onClick={() => {
                      onEffortChange(level.value);
                    }}
                    className={cx(
                      "h-7 rounded-md border text-xs",
                      "transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)]",
                      selected
                        ? "border-ink bg-ink font-medium text-paper"
                        : "border-rule text-muted hover:border-rule-strong hover:text-ink",
                    )}
                  >
                    {level.label}
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
