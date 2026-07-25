import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ChatInput } from "../components/chat/ChatInput";
import { ChatControls } from "../components/chat/ChatControls";
import { Typewriter } from "../components/chat/Typewriter";
import { LogoChip } from "../components/layout/LogoChip";
import { useProjectsStore } from "../stores/projects";
import { useT, type MessageKey } from "../i18n";
import { cx } from "../lib/cx";

/** Nom de projet dérivé des premiers mots du message. */
function deriveName(message: string): string {
  const words = message.trim().split(/\s+/).slice(0, 6).join(" ");
  const name = words.length > 60 ? `${words.slice(0, 57)}…` : words;
  return name.length > 0 ? name : "Nouveau projet";
}

const EXAMPLE_KEYS: MessageKey[] = [
  "home.ex.1",
  "home.ex.2",
  "home.ex.3",
  "home.ex.4",
  "home.ex.5",
  "home.ex.6",
];

/**
 * Accueil « chat d'abord » : une idée décrite ici crée un projet
 * (nom dérivé des premiers mots, description = message complet) puis
 * ouvre sa conversation où le message est envoyé. Le mode / l'exécution /
 * le modèle choisis ici sont repris dans la conversation créée.
 */
export function Home() {
  const navigate = useNavigate();
  const t = useT();
  const create = useProjectsStore((s) => s.create);
  const creating = useProjectsStore((s) => s.creating);
  const [error, setError] = useState<string | null>(null);
  /** Sortie du héros : fondu + léger recul avant de passer au fil. */
  const [leaving, setLeaving] = useState(false);

  const onSend = async (content: string): Promise<void> => {
    setError(null);
    const project = await create({
      name: deriveName(content),
      description: content,
    });
    if (project === null) {
      setError(useProjectsStore.getState().error ?? t("home.createFailed"));
      return;
    }
    setLeaving(true);
    window.setTimeout(() => {
      void navigate(`/chat/${encodeURIComponent(project.id)}`, {
        state: { initialMessage: content },
      });
    }, 200);
  };

  return (
    <div className="flex h-full flex-col items-center justify-center overflow-y-auto px-6">
      <div
        className={cx(
          "flex w-full max-w-2xl flex-col items-center gap-6",
          "transition-[opacity,transform] duration-200 ease-[var(--ease-in)]",
          leaving && "pointer-events-none scale-[0.97] opacity-0",
        )}
      >
        <div className="animate-rise-in">
          <LogoChip className="size-12 animate-breathe rounded-full p-1.5" />
        </div>
        <div className="flex animate-rise-in flex-col items-center gap-2 text-center [animation-delay:80ms]">
          <h1 className="text-2xl text-ink">{t("home.title")}</h1>
          <p className="text-sm text-muted">{t("home.subtitle")}</p>
          <Typewriter
            phrases={EXAMPLE_KEYS.map((k) => t(k))}
            className="min-h-5"
          />
        </div>
        <div className="flex w-full animate-rise-in flex-col gap-3 [animation-delay:160ms]">
          <ChatInput
            onSend={(content) => {
              void onSend(content);
            }}
            disabled={false}
            busy={creating}
            placeholder={t("home.placeholder")}
            autoFocus
            controls={<ChatControls />}
          />
          {error !== null && (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
