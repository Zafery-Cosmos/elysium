import { useCallback, useEffect, useRef, useState } from "react";
import type { ComponentType, FormEvent, SVGProps } from "react";
import { ClaudeLogo, OpenAiLogo } from "../components/ui/BrandLogos";
import { Spinner } from "../components/ui/Spinner";
import { LogoChip } from "../components/layout/LogoChip";
import { useT } from "../i18n";
import type { MessageKey } from "../i18n";
import {
  engine,
  toHumanMessage,
  type CliLogin,
  type CliLoginMode,
} from "../services/engine";
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

const POLL_INTERVAL_MS = 2000;
const POLL_TIMEOUT_MS = 15 * 60 * 1000; // aligné sur l'expiration côté moteur

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

const linkButton =
  "cursor-pointer rounded-md px-2 py-2 text-sm text-muted underline-offset-4 transition-colors duration-[var(--dur-fast)] hover:text-ink hover:underline";

/**
 * Page affichée au tout premier démarrage : connexion avec son compte
 * personnel via Claude Code ou Codex, ou « Passer » pour continuer sans.
 *
 * Le moteur lance la connexion du CLI officiel : le navigateur s'ouvre tout
 * seul. Si le navigateur n'est pas sur cette machine (autre appareil, autre
 * personne), on affiche le lien à copier et un champ pour coller le code — ou
 * l'adresse de redirection 127.0.0.1 — reçu en retour. Aucun jeton ne transite
 * par Elysium : c'est le CLI qui valide.
 */
export function Welcome() {
  const t = useT();
  const completeOnboarding = useUiStore((s) => s.completeOnboarding);
  const [pending, setPending] = useState<CliProvider | null>(null);
  const [login, setLogin] = useState<CliLogin | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [copied, setCopied] = useState(false);
  // Incrémenté à chaque tentative / annulation : invalide les sondages en cours.
  const attempt = useRef(0);

  useEffect(
    () => () => {
      attempt.current += 1; // démontage : stoppe le sondage
    },
    [],
  );

  const failWith = useCallback(
    (err: unknown) => {
      setPending(null);
      setLogin(null);
      // Erreurs du moteur : message déjà lisible ; sinon le détail du CLI.
      const detail =
        err instanceof Error && err.name !== "EngineError"
          ? err.message
          : toHumanMessage(err);
      setError(t("welcome.failed", { detail }));
    },
    [t],
  );

  const connect = useCallback(
    async (id: CliProvider, mode: CliLoginMode = "browser") => {
      const mine = ++attempt.current;
      setPending(id);
      setLogin(null);
      setError(null);
      setCode("");
      setCopied(false);
      try {
        let result = await engine.loginProvider(id, mode);
        const deadline = Date.now() + POLL_TIMEOUT_MS;
        while (result.state === "pending") {
          if (attempt.current !== mine) return;
          setLogin(result);
          if (Date.now() > deadline) throw new Error(t("welcome.timeout"));
          await sleep(POLL_INTERVAL_MS);
          if (attempt.current !== mine) return; // annulé ou terminé ailleurs
          result = await engine.getLogin(id);
        }
        if (attempt.current !== mine) return;
        if (result.state === "signed_in") {
          completeOnboarding(id);
          return;
        }
        throw new Error(result.detail ?? t("welcome.timeout"));
      } catch (err) {
        if (attempt.current !== mine) return;
        failWith(err);
      }
    },
    [completeOnboarding, failWith, t],
  );

  const cancel = () => {
    attempt.current += 1;
    if (pending !== null) void engine.cancelLogin(pending).catch(() => undefined);
    setPending(null);
    setLogin(null);
  };

  const submitCode = async (event: FormEvent) => {
    event.preventDefault();
    const id = pending;
    const value = code.trim();
    if (id === null || value === "" || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await engine.submitLoginCode(id, value);
      if (result.state === "signed_in") {
        attempt.current += 1;
        completeOnboarding(id);
      } else if (result.state === "failed" || result.state === "not_installed") {
        attempt.current += 1;
        failWith(new Error(result.detail ?? t("welcome.timeout")));
      }
      // « pending » : le sondage en cours continue.
    } catch (err) {
      setError(toHumanMessage(err)); // ex. code invalide : on reste sur la page
    } finally {
      setSubmitting(false);
    }
  };

  const copyLink = async () => {
    if (login?.auth_url == null) return;
    try {
      await navigator.clipboard.writeText(login.auth_url);
      setCopied(true);
    } catch {
      /* presse-papiers indisponible : le lien reste copiable à la main */
    }
  };

  const busy = pending !== null;

  return (
    <main className="flex min-h-dvh items-center justify-center bg-paper px-4 py-10">
      <div className="flex w-full max-w-sm animate-rise-in flex-col items-center text-center">
        <LogoChip className="size-14 rounded-xl p-1" />

        <h1 className="mt-6 text-2xl text-ink">{t("welcome.title")}</h1>
        <p className="mt-2 text-base text-muted">{t("welcome.subtitle")}</p>

        <div className="mt-8 flex w-full flex-col gap-3">
          {CHOICES.map(({ id, label, Logo }) => (
            <button
              key={id}
              type="button"
              disabled={busy}
              aria-busy={pending === id || undefined}
              onClick={() => void connect(id)}
              className="flex h-12 w-full cursor-pointer items-center justify-center gap-3 rounded-lg border border-rule bg-paper px-4 text-base font-medium text-ink transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)] hover:border-rule-strong hover:bg-paper-2 active:translate-y-px disabled:cursor-not-allowed disabled:opacity-50"
            >
              {pending === id ? (
                <Spinner className="size-5 shrink-0" />
              ) : (
                <Logo className="size-5 shrink-0" />
              )}
              {t(label)}
            </button>
          ))}
        </div>

        <div
          role="status"
          aria-live="polite"
          className="mt-4 flex w-full min-h-5 flex-col items-center gap-3 text-sm"
        >
          {busy && <p className="text-muted">{t("welcome.waiting")}</p>}

          {busy && login?.device_code != null && (
            <div className="w-full rounded-lg border border-rule bg-paper-2 p-3">
              <p className="text-xs text-muted">{t("welcome.deviceCode")}</p>
              <p className="mt-1 font-mono text-xl tracking-widest text-ink select-all">
                {login.device_code}
              </p>
            </div>
          )}

          {busy && login?.auth_url != null && (
            <button type="button" onClick={() => void copyLink()} className={linkButton}>
              {copied ? t("welcome.copied") : t("welcome.copyLink")}
            </button>
          )}

          {error !== null && <p className="text-danger">{error}</p>}
        </div>

        {busy && login?.accepts_input === true && (
          <details className="mt-1 w-full text-left">
            <summary className="cursor-pointer list-none text-center text-sm text-muted underline-offset-4 hover:text-ink hover:underline">
              {t("welcome.haveCode")}
            </summary>
            <form onSubmit={(e) => void submitCode(e)} className="mt-3 flex flex-col gap-2">
              <label htmlFor="login-code" className="text-xs text-muted">
                {t("welcome.codeLabel")}
              </label>
              <div className="flex gap-2">
                <input
                  id="login-code"
                  type="text"
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  placeholder={t("welcome.codePlaceholder")}
                  autoComplete="off"
                  autoCapitalize="off"
                  spellCheck={false}
                  className="h-11 min-w-0 flex-1 rounded-md border border-rule bg-paper px-3 font-mono text-sm text-ink placeholder:text-neutral"
                />
                <button
                  type="submit"
                  disabled={submitting || code.trim() === ""}
                  className="h-11 shrink-0 cursor-pointer rounded-md bg-accent px-4 text-sm font-medium text-paper transition-colors duration-[var(--dur-fast)] hover:bg-accent/90 disabled:cursor-not-allowed disabled:bg-paper-3 disabled:text-neutral"
                >
                  {submitting ? <Spinner className="size-4" /> : t("welcome.codeSubmit")}
                </button>
              </div>
              <p className="text-xs text-neutral">{t("welcome.codeHelp")}</p>
            </form>
          </details>
        )}

        {busy && pending === "codex" && login?.device_code == null && (
          <button
            type="button"
            onClick={() => void connect("codex", "device")}
            className={`mt-1 ${linkButton}`}
          >
            {t("welcome.deviceLink")}
          </button>
        )}

        {busy ? (
          <button type="button" onClick={cancel} className={`mt-2 h-11 ${linkButton}`}>
            {t("welcome.cancel")}
          </button>
        ) : (
          <button
            type="button"
            onClick={() => completeOnboarding()}
            className={`mt-2 h-11 ${linkButton}`}
          >
            {t("welcome.skip")}
          </button>
        )}

        <p className="mt-6 text-xs text-neutral">{t("welcome.hint")}</p>
      </div>
    </main>
  );
}
