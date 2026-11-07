import { useState } from "react";
import { CLI_LABELS, type CliSignIn } from "../../hooks/useCliSignIn";
import { useT } from "../../i18n";
import { describeAccount } from "../../lib/account";
import { Spinner } from "./Spinner";

const linkButton =
  "cursor-pointer rounded-md px-2 py-2 text-sm text-muted underline-offset-4 transition-colors duration-[var(--dur-fast)] hover:text-ink hover:underline";

/**
 * Étape « compte déjà connecté » : on dit QUEL compte est détecté et on laisse
 * choisir. Changer de compte déconnecte aussi le CLI dans le terminal de
 * l'utilisateur (la session est partagée) — d'où la confirmation.
 */
export function ExistingAccountPanel({ s }: { s: CliSignIn }) {
  const t = useT();
  const [confirmSwitch, setConfirmSwitch] = useState(false);
  if (s.existing === null) return null;
  const { id, account } = s.existing;
  const label = CLI_LABELS[id];
  return (
    <div className="w-full rounded-lg border border-rule bg-paper-2 p-4 text-left" role="group">
      <p className="text-sm font-medium text-ink">{t("welcome.account.title", { provider: label })}</p>
      <p className="mt-1 break-words text-sm text-muted">{describeAccount(account, t)}</p>
      <p className="mt-2 text-xs text-neutral">{t("welcome.account.shared", { provider: label })}</p>
      <div className="mt-4 flex flex-col gap-2">
        <button
          type="button"
          onClick={s.useExisting}
          className="h-11 cursor-pointer rounded-md bg-accent px-4 text-sm font-medium text-paper transition-colors duration-[var(--dur-fast)] hover:bg-accent/90"
        >
          {t("welcome.account.use")}
        </button>
        {confirmSwitch ? (
          <div className="rounded-md border border-danger/40 p-3">
            <p className="text-xs text-danger">{t("welcome.account.switchWarn", { provider: label })}</p>
            <button
              type="button"
              onClick={() => void s.connect(id, "browser", true)}
              className="mt-2 h-10 w-full cursor-pointer rounded-md border border-danger/40 px-3 text-sm text-danger transition-colors hover:bg-danger/10"
            >
              {t("welcome.account.switchConfirm")}
            </button>
          </div>
        ) : (
          <button type="button" onClick={() => setConfirmSwitch(true)} className={linkButton}>
            {t("welcome.account.switch")}
          </button>
        )}
      </div>
    </div>
  );
}

/** Attente de connexion : lien à copier, code appareil, saisie d'un code, annulation. */
export function SignInProgress({ s }: { s: CliSignIn }) {
  const t = useT();
  const { login } = s;
  if (!s.busy && s.error === null) return null;
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex w-full min-h-5 flex-col items-center gap-3 text-sm"
    >
      {s.busy && (
        <p className="flex items-center gap-2 text-muted">
          <Spinner className="size-4" />
          {t("welcome.waiting")}
        </p>
      )}

      {s.busy && login?.device_code != null && (
        <div className="w-full rounded-lg border border-rule bg-paper-2 p-3 text-center">
          <p className="text-xs text-muted">{t("welcome.deviceCode")}</p>
          <p className="mt-1 select-all font-mono text-xl tracking-widest text-ink">
            {login.device_code}
          </p>
        </div>
      )}

      {s.busy && login?.auth_url != null && (
        <button type="button" onClick={() => void s.copyLink()} className={linkButton}>
          {s.copied ? t("welcome.copied") : t("welcome.copyLink")}
        </button>
      )}

      {s.error !== null && <p className="text-center text-danger">{s.error}</p>}

      {s.busy && login?.accepts_input === true && (
        <details className="w-full text-left">
          <summary className="cursor-pointer list-none text-center text-sm text-muted underline-offset-4 hover:text-ink hover:underline">
            {t("welcome.haveCode")}
          </summary>
          <form onSubmit={(e) => void s.submitCode(e)} className="mt-3 flex flex-col gap-2">
            <label htmlFor="login-code" className="text-xs text-muted">
              {t("welcome.codeLabel")}
            </label>
            <div className="flex gap-2">
              <input
                id="login-code"
                type="text"
                value={s.code}
                onChange={(e) => s.setCode(e.target.value)}
                placeholder={t("welcome.codePlaceholder")}
                autoComplete="off"
                autoCapitalize="off"
                spellCheck={false}
                className="h-11 min-w-0 flex-1 rounded-md border border-rule bg-paper px-3 font-mono text-sm text-ink placeholder:text-neutral"
              />
              <button
                type="submit"
                disabled={s.submitting || s.code.trim() === ""}
                className="h-11 shrink-0 cursor-pointer rounded-md bg-accent px-4 text-sm font-medium text-paper transition-colors duration-[var(--dur-fast)] hover:bg-accent/90 disabled:cursor-not-allowed disabled:bg-paper-3 disabled:text-neutral"
              >
                {s.submitting ? <Spinner className="size-4" /> : t("welcome.codeSubmit")}
              </button>
            </div>
            <p className="text-xs text-neutral">{t("welcome.codeHelp")}</p>
          </form>
        </details>
      )}

      {s.busy && s.pending === "codex" && login?.device_code == null && (
        <button type="button" onClick={() => void s.connect("codex", "device")} className={linkButton}>
          {t("welcome.deviceLink")}
        </button>
      )}

      {s.busy && (
        <button type="button" onClick={s.cancel} className={`h-11 ${linkButton}`}>
          {t("welcome.cancel")}
        </button>
      )}
    </div>
  );
}
