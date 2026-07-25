import { useT, type MessageKey } from "../../i18n";
import { cx } from "../../lib/cx";

const SUGGESTION_KEYS: MessageKey[] = [
  "chat.suggestion.1",
  "chat.suggestion.2",
  "chat.suggestion.3",
  "chat.suggestion.4",
];

/**
 * Suggestions cliquables au-dessus de la saisie quand la conversation
 * est vide : le clic préremplit le champ (aucun envoi automatique).
 */
export function Suggestions({ onPick }: { onPick: (text: string) => void }) {
  const t = useT();
  return (
    <div aria-label={t("chat.suggestions.aria")} className="mb-3 flex flex-wrap gap-2">
      {SUGGESTION_KEYS.map((key, index) => {
        const text = t(key);
        return (
          <button
            key={key}
            type="button"
            onClick={() => {
              onPick(text);
            }}
            style={{ animationDelay: `${String(index * 50)}ms` }}
            className={cx(
              "animate-rise-in rounded-full border border-rule bg-paper px-3 py-1.5 text-xs text-muted",
              "transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)]",
              "hover:border-rule-strong hover:bg-paper-2 hover:text-ink",
            )}
          >
            {text}
          </button>
        );
      })}
    </div>
  );
}
