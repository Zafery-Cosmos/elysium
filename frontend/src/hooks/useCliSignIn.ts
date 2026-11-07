import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { useT } from "../i18n";
import {
  engine,
  toHumanMessage,
  type CliAccount,
  type CliLogin,
  type CliLoginMode,
} from "../services/engine";
import type { CliProvider } from "../stores/ui";

const POLL_INTERVAL_MS = 2000;
const POLL_TIMEOUT_MS = 15 * 60 * 1000; // aligné sur l'expiration côté moteur

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

export const CLI_LABELS: Record<CliProvider, string> = {
  "claude-code": "Claude Code",
  codex: "Codex",
};

/** Session déjà ouverte sur cet ordinateur, en attente du choix de l'utilisateur. */
export interface ExistingSession {
  id: CliProvider;
  account: CliAccount | null;
}

/**
 * Connexion à un abonnement via le CLI officiel (Claude Code / Codex).
 *
 * - Si une session existe déjà sur la machine, RIEN n'est lancé : `existing`
 *   décrit le compte détecté et l'utilisateur choisit (l'utiliser / en changer).
 * - Sinon le navigateur s'ouvre, on sonde jusqu'à la connexion ; si le
 *   navigateur n'est pas sur cette machine, le lien se copie et un code (ou
 *   l'adresse 127.0.0.1) se colle. Aucun jeton ne transite par Elysium.
 */
export function useCliSignIn(onSignedIn: (id: CliProvider) => void) {
  const t = useT();
  const [pending, setPending] = useState<CliProvider | null>(null);
  const [login, setLogin] = useState<CliLogin | null>(null);
  const [existing, setExisting] = useState<ExistingSession | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [copied, setCopied] = useState(false);
  // Incrémenté à chaque tentative / annulation : invalide les sondages en cours.
  const attempt = useRef(0);
  const onSignedInRef = useRef(onSignedIn);
  onSignedInRef.current = onSignedIn;

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
    async (id: CliProvider, mode: CliLoginMode = "browser", force = false) => {
      const mine = ++attempt.current;
      setPending(id);
      setLogin(null);
      setExisting(null);
      setError(null);
      setCode("");
      setCopied(false);
      try {
        let result = await engine.loginProvider(id, mode, force);
        if (attempt.current !== mine) return;
        if (result.state === "signed_in" && result.already_signed_in === true) {
          // Une session existe déjà : on montre LEQUEL, on ne fait pas semblant.
          setPending(null);
          setExisting({ id, account: result.account ?? null });
          return;
        }
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
          onSignedInRef.current(id);
          return;
        }
        throw new Error(result.detail ?? t("welcome.timeout"));
      } catch (err) {
        if (attempt.current !== mine) return;
        failWith(err);
      }
    },
    [failWith, t],
  );

  const useExisting = useCallback(() => {
    if (existing === null) return;
    const id = existing.id;
    setExisting(null);
    onSignedInRef.current(id);
  }, [existing]);

  const cancel = useCallback(() => {
    attempt.current += 1;
    if (pending !== null) void engine.cancelLogin(pending).catch(() => undefined);
    setPending(null);
    setLogin(null);
    setExisting(null);
  }, [pending]);

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
        onSignedInRef.current(id);
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

  return {
    pending,
    login,
    existing,
    error,
    code,
    setCode,
    submitting,
    copied,
    busy: pending !== null,
    connect,
    useExisting,
    cancel,
    submitCode,
    copyLink,
  };
}

export type CliSignIn = ReturnType<typeof useCliSignIn>;
