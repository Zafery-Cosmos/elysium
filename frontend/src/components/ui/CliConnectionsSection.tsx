import { useCallback, useEffect, useState } from "react";
import type { ComponentType, SVGProps } from "react";
import { CLI_LABELS } from "../../hooks/useCliSignIn";
import { useT } from "../../i18n";
import { describeAccount } from "../../lib/account";
import { engine, type CliLogin } from "../../services/engine";
import type { CliProvider } from "../../stores/ui";
import { Badge } from "./Badge";
import { ClaudeLogo, OpenAiLogo } from "./BrandLogos";
import { CliAccountActions } from "./CliAccountActions";

const PROVIDERS: Array<{ id: CliProvider; Logo: ComponentType<SVGProps<SVGSVGElement>> }> = [
  { id: "claude-code", Logo: ClaudeLogo },
  { id: "codex", Logo: OpenAiLogo },
];

function Card({ id, Logo }: { id: CliProvider; Logo: ComponentType<SVGProps<SVGSVGElement>> }) {
  const t = useT();
  const [login, setLogin] = useState<CliLogin | null>(null);
  const refresh = useCallback(() => {
    void engine
      .getLogin(id)
      .then(setLogin)
      .catch(() => setLogin(null));
  }, [id]);
  useEffect(() => {
    refresh();
  }, [refresh]);

  const signedIn = login === null ? null : login.state === "signed_in";
  const installed = login?.state !== "not_installed" && !/not installed/i.test(login?.detail ?? "");

  return (
    <article className="flex flex-col gap-2 rounded-lg border border-rule bg-paper-2/50 px-5 py-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="flex items-center gap-2 text-sm font-medium text-ink">
          <Logo className="size-4 shrink-0" />
          {CLI_LABELS[id]}
        </h3>
        {login !== null && (
          <Badge tone={signedIn === true ? "ok" : "muted"} live={signedIn === true}>
            {signedIn === true ? t("admin.signedIn") : t("admin.signedOut")}
          </Badge>
        )}
      </div>
      {signedIn === true && (
        <p className="break-words text-xs text-ink">{describeAccount(login?.account, t)}</p>
      )}
      <p className="text-xs text-neutral">{t("admin.connections.hint")}</p>
      <CliAccountActions id={id} signedIn={signedIn} installed={installed} onChanged={refresh} />
    </article>
  );
}

/** « Connexion par abonnement » : Claude Code et Codex, connectables à tout moment. */
export function CliConnectionsSection() {
  const t = useT();
  return (
    <section
      aria-label={t("models.subscription")}
      className="flex animate-rise-in flex-col gap-3 [animation-delay:40ms]"
    >
      <h2 className="text-sm font-medium text-muted">{t("models.subscription")}</h2>
      <p className="max-w-2xl text-xs text-neutral">{t("models.subscription.hint")}</p>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {PROVIDERS.map(({ id, Logo }) => (
          <Card key={id} id={id} Logo={Logo} />
        ))}
      </div>
    </section>
  );
}
