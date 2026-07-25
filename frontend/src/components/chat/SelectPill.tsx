import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { cx } from "../../lib/cx";
import { IconCheck, IconChevronDown } from "../layout/icons";

export interface PillOption<T extends string> {
  value: T;
  label: string;
  hint?: string;
}

/**
 * Pastille compacte ouvrant un petit panneau de choix — même famille visuelle
 * que ModelPicker. La pastille montre la valeur courante + un chevron ; le
 * panneau liste les options (radiogroup). Échap ferme (retour du focus), clic
 * à l'extérieur ferme, ↑/↓ naviguent entre les options.
 */
export function SelectPill<T extends string>({
  ariaLabel,
  title,
  value,
  options,
  onChange,
  disabled = false,
  leading,
  placement = "top",
}: {
  /** Libellé accessible du contrôle (ex. « Mode de conversation »). */
  ariaLabel: string;
  /** Infobulle décrivant le contrôle. */
  title?: string;
  value: T;
  options: Array<PillOption<T>>;
  onChange: (value: T) => void;
  disabled?: boolean;
  /** Élément décoratif optionnel devant la valeur (ex. un point). */
  leading?: ReactNode;
  /** Sens d'ouverture du panneau. */
  placement?: "top" | "bottom";
}) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  const current = options.find((o) => o.value === value) ?? options[0];

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

  const onPanelKeyDown = (e: KeyboardEvent<HTMLDivElement>): void => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const panel = panelRef.current;
    if (panel === null) return;
    const items = [
      ...panel.querySelectorAll<HTMLButtonElement>("button[data-option]"),
    ];
    if (items.length === 0) return;
    e.preventDefault();
    const index = items.findIndex((o) => o === document.activeElement);
    const delta = e.key === "ArrowDown" ? 1 : -1;
    const next =
      index === -1 ? 0 : (index + delta + items.length) % items.length;
    items[next]?.focus();
  };

  return (
    <div ref={containerRef} className="relative">
      <button
        ref={buttonRef}
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={`${ariaLabel} : ${current?.label ?? ""}`}
        title={title}
        disabled={disabled}
        onClick={() => {
          setOpen((v) => !v);
        }}
        className={cx(
          "flex h-6 items-center gap-1 rounded-full border border-rule bg-paper pr-1.5 pl-2.5 text-xs",
          "transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)]",
          "hover:border-rule-strong hover:bg-paper-2",
          "disabled:cursor-not-allowed disabled:opacity-60",
          open && "border-rule-strong bg-paper-2",
        )}
      >
        {leading}
        <span className="max-w-32 truncate text-ink">
          {current?.label ?? ""}
        </span>
        <IconChevronDown
          width={11}
          height={11}
          className={cx(
            "text-neutral transition-transform duration-[var(--dur-fast)] ease-[var(--ease-out)]",
            open && "rotate-180",
          )}
        />
      </button>

      {open && (
        <div
          ref={panelRef}
          role="dialog"
          aria-label={ariaLabel}
          onKeyDown={onPanelKeyDown}
          className={cx(
            "absolute left-0 z-30 w-64 animate-rise-in",
            "rounded-xl border border-rule bg-paper p-1.5 shadow-lg shadow-ink/10",
            placement === "top" ? "bottom-full mb-2" : "top-full mt-2",
          )}
        >
          {options.map((option) => {
            const selected = option.value === value;
            return (
              <button
                key={option.value}
                type="button"
                data-option
                role="radio"
                aria-checked={selected}
                onClick={() => {
                  onChange(option.value);
                  setOpen(false);
                  buttonRef.current?.focus();
                }}
                className={cx(
                  "flex w-full items-start gap-2 rounded-md px-2.5 py-1.5 text-left",
                  "transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)] hover:bg-paper-3",
                  selected && "bg-paper-3",
                )}
              >
                <span className="min-w-0 flex-1">
                  <span
                    className={cx(
                      "block text-sm text-ink",
                      selected && "font-medium",
                    )}
                  >
                    {option.label}
                  </span>
                  {option.hint !== undefined && (
                    <span className="mt-0.5 block text-xs text-neutral">
                      {option.hint}
                    </span>
                  )}
                </span>
                {selected && (
                  <IconCheck
                    width={13}
                    height={13}
                    className="mt-0.5 shrink-0 text-ink"
                  />
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
