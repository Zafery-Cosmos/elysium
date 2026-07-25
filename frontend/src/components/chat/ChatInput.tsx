import { useState, type FormEvent, type KeyboardEvent } from "react";
import { IconSend } from "../layout/icons";
import { cx } from "../../lib/cx";

export function ChatInput({
  onSend,
  disabled,
  busy,
}: {
  onSend: (content: string) => void;
  disabled: boolean;
  busy: boolean;
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
    <form
      onSubmit={onSubmit}
      className="border-t border-rule bg-paper px-6 py-4"
    >
      <div
        className={cx(
          "flex items-end gap-2 rounded-lg border border-rule bg-paper-2 p-2",
          "transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)]",
          "focus-within:border-rule-strong",
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
          placeholder="Décrivez ce que vous voulez construire — l'équipe s'occupe du reste."
          aria-label="Votre message à l'équipe"
          className="max-h-48 min-h-10 flex-1 resize-none bg-transparent px-2 py-1.5 text-sm text-ink outline-none placeholder:text-neutral disabled:cursor-not-allowed"
        />
        <button
          type="submit"
          disabled={disabled || busy || value.trim().length === 0}
          aria-label="Envoyer le message"
          className={cx(
            "grid size-9 shrink-0 place-items-center rounded-md bg-accent text-paper",
            "transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)]",
            "hover:bg-accent/90 active:translate-y-px",
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
