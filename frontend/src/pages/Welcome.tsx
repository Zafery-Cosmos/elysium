import type { ComponentType, SVGProps } from "react";
import { ClaudeLogo, OpenAiLogo } from "../components/ui/BrandLogos";
import { ExistingAccountPanel, SignInProgress } from "../components/ui/CliSignInPanel";
import { Spinner } from "../components/ui/Spinner";
import { LogoChip } from "../components/layout/LogoChip";
import { useCliSignIn } from "../hooks/useCliSignIn";
import { useT } from "../i18n";
import type { MessageKey } from "../i18n";
import { useUiStore, type CliProvider } from "../stores/ui";

interface ProviderChoice {
  id: CliProvider;
  label: MessageKey;
  Logo: ComponentType<SVGProps<SVGSVGElement>>;
}

const CHOICES: ProviderChoice[] = [
  { id: "claude-code", label: "welcome.claude", Logo: ClaudeLogo },
  { id: "codex", label: "welcome.codex", Logo: OpenAiLogo },
];

/**
 * Page affichée au tout premier démarrage : connexion avec son compte
 * personnel via Claude Code ou Codex, ou « Passer » pour continuer sans.
 *
 * Si une session existe déjà sur l'ordinateur (ex. Claude Code déjà connecté
 * dans le terminal), on l'indique avec le compte détecté et on laisse choisir
 * au lieu de passer silencieusement à l'application.
 */
export function Welcome() {
  const t = useT();
  const completeOnboarding = useUiStore((s) => s.completeOnboarding);
  const s = useCliSignIn((id) => {
    completeOnboarding(id);
  });

  return (
    <main className="flex min-h-dvh items-center justify-center bg-paper px-4 py-10">
      <div className="flex w-full max-w-sm animate-rise-in flex-col items-center text-center">
        <LogoChip className="size-14 rounded-xl p-1" />

        <h1 className="mt-6 text-2xl text-ink">{t("welcome.title")}</h1>
        <p className="mt-2 text-base text-muted">{t("welcome.subtitle")}</p>

        {s.existing !== null ? (
          <div className="mt-8 w-full">
            <ExistingAccountPanel s={s} />
          </div>
        ) : (
          <div className="mt-8 flex w-full flex-col gap-3">
            {CHOICES.map(({ id, label, Logo }) => (
              <button
                key={id}
                type="button"
                disabled={s.busy}
                aria-busy={s.pending === id || undefined}
                onClick={() => void s.connect(id)}
                className="flex h-12 w-full cursor-pointer items-center justify-center gap-3 rounded-lg border border-rule bg-paper px-4 text-base font-medium text-ink transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)] hover:border-rule-strong hover:bg-paper-2 active:translate-y-px disabled:cursor-not-allowed disabled:opacity-50"
              >
                {s.pending === id ? (
                  <Spinner className="size-5 shrink-0" />
                ) : (
                  <Logo className="size-5 shrink-0" />
                )}
                {t(label)}
              </button>
            ))}
          </div>
        )}

        <div className="mt-4 w-full">
          <SignInProgress s={s} />
        </div>

        {!s.busy && (
          <button
            type="button"
            onClick={() => completeOnboarding()}
            className="mt-2 h-11 cursor-pointer rounded-md px-2 text-sm text-muted underline-offset-4 transition-colors duration-[var(--dur-fast)] hover:text-ink hover:underline"
          >
            {t("welcome.skip")}
          </button>
        )}

        <p className="mt-6 text-xs text-neutral">{t("welcome.hint")}</p>
      </div>
    </main>
  );
}
