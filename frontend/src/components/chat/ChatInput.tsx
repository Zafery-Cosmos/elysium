import { useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import { IconSend } from "../layout/icons";
import { useT } from "../../i18n";
import { cx } from "../../lib/cx";

/**
 * Zone de saisie du chat — même boîte sur l'accueil (héros) et dans un fil.
 * Entrée envoie, Maj+Entrée insère un saut de ligne.
 * Contrôlable de l'extérieur via `value`/`onValueChange` (suggestions).
 *
 * `controls` (optionnel) : bande de contrôles (Mode/Exécution/Modèle) rendue
 * DANS la même boîte bordée, sous la ligne de saisie — cf. Home.tsx/Chat.tsx.
 */
export function ChatInput({
  onSend,
  disabled,
  busy,
  placeholder,
  autoFocus = false,
  value: controlledValue,
  onValueChange,
  controls,
}: {
  onSend: (content: string) => void;
  disabled: boolean;
  busy: boolean;
  placeholder?: string;
  autoFocus?: boolean;
  /** Si fournie, la saisie est contrôlée par le parent. */
  value?: string;
  onValueChange?: (value: string) => void;
  /** Bande de contrôles affichée sous la saisie, dans la même boîte. */
  controls?: ReactNode;
}) {
  const t = useT();
  const [innerValue, setInnerValue] = useState("");
  const value = controlledValue ?? innerValue;
  const setValue = (next: string): void => {
    onValueChange?.(next);
    if (controlledValue === undefined) setInnerValue(next);
  };

  const submit = (): void => {
    const trimmed = value.trim();
    if (trimmed.length === 0 || disabled || busy) return;
    onSend(trimmed);
    setValue("");
  };

  const onSubmit = (e: FormEvent): void => {
    e.preventDefault();
    submit();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>): void => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <form onSubmit={onSubmit} className="w-full">
      <div
        className={cx(
          "flex flex-col rounded-xl border border-rule bg-paper p-2 shadow-sm",
          "transition-[border-color,box-shadow] duration-[var(--dur-base)] ease-[var(--ease-out)]",
          "focus-within:border-rule-strong focus-within:shadow-md",
        )}
      >
        <div className="flex items-end gap-2">
          <textarea
            value={value}
            onChange={(e) => {
              setValue(e.target.value);
            }}
            onKeyDown={onKeyDown}
            rows={2}
            disabled={disabled}
            autoFocus={autoFocus}
            placeholder={placeholder ?? t("chat.input.placeholder")}
            aria-label={t("chat.input.aria")}
            className="max-h-48 min-h-10 flex-1 resize-none bg-transparent px-2 py-1.5 text-sm text-ink outline-none placeholder:text-neutral disabled:cursor-not-allowed"
          />
          <button
            type="submit"
            disabled={disabled || busy || value.trim().length === 0}
            aria-label={t("chat.input.send")}
            className={cx(
              "grid size-9 shrink-0 place-items-center rounded-full bg-ink text-paper",
              "transition-[background-color,transform] duration-[var(--dur-fast)] ease-[var(--ease-out)]",
              "hover:scale-105 hover:bg-ink/85 active:scale-95",
              "disabled:cursor-not-allowed disabled:bg-paper-3 disabled:text-neutral",
            )}
          >
            <IconSend width={16} height={16} />
          </button>
        </div>
        {controls !== undefined && (
          <div className="mt-2 flex flex-wrap items-center gap-1.5 border-t border-rule px-1 pt-2">
            {controls}
          </div>
        )}
      </div>
      <p className="mt-2 text-xs text-neutral">{t("chat.input.hint")}</p>
    </form>
  );
}
