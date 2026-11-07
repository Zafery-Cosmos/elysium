import { useState, type FormEvent } from "react";
import { CLI_LABELS } from "../../hooks/useCliSignIn";
import { useT } from "../../i18n";
import { engine, EngineError, toHumanMessage } from "../../services/engine";
import type { CliProvider } from "../../stores/ui";
import { Spinner } from "./Spinner";

/**
 * Connexion par jeton collé (compte PERSONNEL de l'utilisateur) :
 * - Claude Code : le jeton affiché par `claude setup-token`.
 * - Codex : le contenu de `auth.json` (écrit par `codex login`).
 * Le jeton est vérifié auprès du vrai CLI avant d'être conservé ; il n'est
 * jamais réaffiché ni écrit dans les journaux.
 */
export function TokenImport({
  id,
  onDone,
}: {
  id: CliProvider;
  onDone: () => void;
}) {
  const t = useT();
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isClaude = id === "claude-code";

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy || value.trim() === "") return;
    setBusy(true);
    setError(null);
    try {
      const result = await engine.importProviderToken(id, value.trim());
      if (result.state === "signed_in") {
        setValue(""); // le jeton ne reste pas dans l'interface
        onDone();
      } else {
        setError(result.detail ?? t("token.failed"));
      }
    } catch (err) {
      setError(err instanceof EngineError ? err.humanMessage : toHumanMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <details className="w-full text-left">
      <summary className="cursor-pointer list-none text-center text-sm text-muted underline-offset-4 hover:text-ink hover:underline">
        {t("token.summary", { provider: CLI_LABELS[id] })}
      </summary>
      <form onSubmit={(e) => void submit(e)} className="mt-3 flex flex-col gap-2">
        <p className="text-xs text-muted">
          {isClaude ? t("token.claude.how") : t("token.codex.how")}
        </p>
        {isClaude ? (
          <input
            type="password"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="sk-ant-…"
            aria-label={t("token.label", { provider: CLI_LABELS[id] })}
            autoComplete="off"
            spellCheck={false}
            className="h-11 rounded-md border border-rule bg-paper px-3 font-mono text-sm text-ink placeholder:text-neutral"
          />
        ) : (
          <textarea
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder='{ "tokens": { … } }'
            aria-label={t("token.label", { provider: CLI_LABELS[id] })}
            autoComplete="off"
            spellCheck={false}
            rows={4}
            className="rounded-md border border-rule bg-paper px-3 py-2 font-mono text-xs text-ink placeholder:text-neutral"
          />
        )}
        <button
          type="submit"
          disabled={busy || value.trim() === ""}
          className="h-10 cursor-pointer rounded-md bg-accent px-4 text-sm font-medium text-paper transition-colors hover:bg-accent/90 disabled:cursor-not-allowed disabled:bg-paper-3 disabled:text-neutral"
        >
          {busy ? <Spinner className="mx-auto size-4" /> : t("token.submit")}
        </button>
        {busy && isClaude && <p className="text-xs text-neutral">{t("token.verifying")}</p>}
        {error !== null && (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        )}
        <p className="text-xs text-neutral">{t("token.warning")}</p>
      </form>
    </details>
  );
}
