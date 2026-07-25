import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ChatInput } from "../components/chat/ChatInput";
import { LogoChip } from "../components/layout/LogoChip";
import { useProjectsStore } from "../stores/projects";

/** Nom de projet dérivé des premiers mots du message. */
function deriveName(message: string): string {
  const words = message.trim().split(/\s+/).slice(0, 6).join(" ");
  const name = words.length > 60 ? `${words.slice(0, 57)}…` : words;
  return name.length > 0 ? name : "Nouveau projet";
}

/**
 * Accueil « chat d'abord » : une idée décrite ici crée un projet
 * (nom dérivé des premiers mots, description = message complet) puis
 * ouvre sa conversation où le message est envoyé.
 */
export function Home() {
  const navigate = useNavigate();
  const create = useProjectsStore((s) => s.create);
  const creating = useProjectsStore((s) => s.creating);
  const [error, setError] = useState<string | null>(null);

  const onSend = async (content: string): Promise<void> => {
    setError(null);
    const project = await create({
      name: deriveName(content),
      description: content,
    });
    if (project === null) {
      setError(
        useProjectsStore.getState().error ??
          "La création du projet a échoué. Réessayez.",
      );
      return;
    }
    void navigate(`/chat/${encodeURIComponent(project.id)}`, {
      state: { initialMessage: content },
    });
  };

  return (
    <div className="flex h-full flex-col items-center justify-center overflow-y-auto px-6">
      <div className="flex w-full max-w-2xl animate-fade-in flex-col items-center gap-6">
        <LogoChip className="size-12 rounded-full p-1.5" />
        <div className="flex flex-col items-center gap-2 text-center">
          <h1 className="text-2xl text-ink">Que voulez-vous créer ?</h1>
          <p className="text-sm text-muted">
            Décrivez votre idée, l'équipe Elysium s'occupe du reste.
          </p>
        </div>
        <div className="w-full">
          <ChatInput
            onSend={(content) => {
              void onSend(content);
            }}
            disabled={false}
            busy={creating}
            placeholder="Une application pour réserver des restaurants…"
            autoFocus
          />
          {error !== null && (
            <p role="alert" className="mt-2 text-sm text-danger">
              {error}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
