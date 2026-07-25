import { cx } from "../../lib/cx";

const SUGGESTIONS: string[] = [
  "Créer une application web de réservation",
  "Analyser un projet existant",
  "Faire le plan de mon idée",
  "Créer une API + base de données",
];

/**
 * Suggestions cliquables au-dessus de la saisie quand la conversation
 * est vide : le clic préremplit le champ (aucun envoi automatique).
 */
export function Suggestions({ onPick }: { onPick: (text: string) => void }) {
  return (
    <div
      aria-label="Suggestions de démarrage"
      className="mb-3 flex flex-wrap gap-2"
    >
      {SUGGESTIONS.map((text, index) => (
        <button
          key={text}
          type="button"
          onClick={() => {
            onPick(text);
          }}
          style={{ animationDelay: `${index * 50}ms` }}
          className={cx(
            "animate-rise-in rounded-full border border-rule bg-paper px-3 py-1.5 text-xs text-muted",
            "transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)]",
            "hover:border-rule-strong hover:bg-paper-2 hover:text-ink",
          )}
        >
          {text}
        </button>
      ))}
    </div>
  );
}
