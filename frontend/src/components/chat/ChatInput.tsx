import { useState, type FormEvent, type KeyboardEvent } from "react";
import { IconSend } from "../layout/icons";
import { cx } from "../../lib/cx";

/**
 * Zone de saisie du chat — même boîte sur l'accueil (héros) et dans un fil.
 * Entrée envoie, Maj+Entrée insère un saut de ligne.
 */
export function ChatInput({
  onSend,
  disabled,
  busy,
  placeholder = "Décrivez ce que vous voulez construire — l'équipe s'occupe du reste.",
  autoFocus = false,
}: {
  onSend: (content: string) => void;
  disabled: boolean;
  busy: boolean;
  placeholder?: string;
  autoFocus?: boolean;
}) {
  const [value, setValue] = useState("");

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
          "flex items-end gap-2 rounded-xl border border-rule bg-paper p-2 shadow-sm",
          "transition-[border-color,box-shadow] duration-[var(--dur-base)] ease-[var(--ease-out)]",
          "focus-within:border-rule-strong focus-within:shadow-md",
        )}
      >
        <textarea
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
          }}
          onKeyDown={onKeyDown}
          rows={2}
          disabled={disabled}
          autoFocus={autoFocus}
          placeholder={placeholder}
          aria-label="Votre message à l'équipe"
          className="max-h-48 min-h-10 flex-1 resize-none bg-transparent px-2 py-1.5 text-sm text-ink outline-none placeholder:text-neutral disabled:cursor-not-allowed"
        />
        <button
          type="submit"
          disabled={disabled || busy || value.trim().length === 0}
          aria-label="Envoyer le message"
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
      <p className="mt-2 text-xs text-neutral">
        Entrée pour envoyer · Maj+Entrée pour une nouvelle ligne
      </p>
    </form>
  );
}
