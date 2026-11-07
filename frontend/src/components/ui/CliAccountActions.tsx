import { useCallback, useEffect, useRef, useState } from "react";
import { CLI_LABELS, useCliSignIn } from "../../hooks/useCliSignIn";
import { useT } from "../../i18n";
import { engine } from "../../services/engine";
import type { CliProvider } from "../../stores/ui";
import { ConfirmDialog } from "./ConfirmDialog";
import { ExistingAccountPanel, SignInProgress } from "./CliSignInPanel";
import { Modal } from "./Modal";
import { TokenImport } from "./TokenImport";

const actionBtn =
  "h-8 cursor-pointer rounded-md border border-rule px-3 text-xs text-ink transition-colors duration-[var(--dur-fast)] hover:border-rule-strong hover:bg-paper-2";

/** Contenu de la fenêtre de connexion : démarre la connexion une seule fois. */
function SignInModalBody({
  id,
  force,
  onDone,
}: {
  id: CliProvider;
  force: boolean;
  onDone: () => void;
}) {
  const s = useCliSignIn(onDone);
  const started = useRef(false);
  const { connect } = s;
  useEffect(() => {
    if (started.current) return; // StrictMode monte deux fois : une seule connexion
    started.current = true;
    void connect(id, "browser", force);
  }, [connect, id, force]);
  return (
    <div className="flex flex-col items-center gap-3">
      <ExistingAccountPanel s={s} />
      <SignInProgress s={s} />
      <TokenImport id={id} onDone={onDone} />
    </div>
  );
}

/**
 * Boutons de connexion d'un abonnement (Claude Code / Codex), utilisables À TOUT
 * MOMENT : se connecter, changer de compte, se déconnecter. La session est celle
 * d'Elysium, séparée du Claude Code / Codex du terminal.
 */
export function CliAccountActions({
  id,
  signedIn,
  installed,
  onChanged,
}: {
  id: CliProvider;
  signedIn: boolean | null;
  installed: boolean;
  onChanged: () => void;
}) {
  const t = useT();
  const label = CLI_LABELS[id];
  const [signIn, setSignIn] = useState<{ force: boolean; key: number } | null>(null);
  const [confirmOut, setConfirmOut] = useState(false);
  const [busy, setBusy] = useState(false);

  const closeSignIn = useCallback(() => {
    // Fermer la fenêtre annule la connexion en cours côté moteur.
    setSignIn(null);
    void engine.cancelLogin(id).catch(() => undefined);
    onChanged();
  }, [id, onChanged]);

  if (!installed) {
    return <p className="mt-2 text-xs text-neutral">{t("admin.notInstalled", { provider: label })}</p>;
  }

  return (
    <>
      <div className="mt-2 flex flex-wrap gap-2">
        {signedIn === true ? (
          <>
            <button
              type="button"
              className={actionBtn}
              onClick={() => setSignIn({ force: true, key: Date.now() })}
            >
              {t("admin.switchAccount")}
            </button>
            <button type="button" className={actionBtn} onClick={() => setConfirmOut(true)}>
              {t("admin.signOut")}
            </button>
          </>
        ) : (
          <button
            type="button"
            className={actionBtn}
            onClick={() => setSignIn({ force: false, key: Date.now() })}
          >
            {t("admin.signIn")}
          </button>
        )}
      </div>

      <Modal
        open={signIn !== null}
        title={t("admin.signin.title", { provider: label })}
        onClose={closeSignIn}
      >
        {signIn !== null && (
          <SignInModalBody
            key={signIn.key}
            id={id}
            force={signIn.force}
            onDone={() => {
              setSignIn(null);
              onChanged();
            }}
          />
        )}
      </Modal>

      <ConfirmDialog
        open={confirmOut}
        danger={false}
        busy={busy}
        title={t("admin.signOut.title", { provider: label })}
        body={t("admin.signOut.body", { provider: label })}
        confirmLabel={t("admin.signOut")}
        cancelLabel={t("welcome.cancel")}
        onConfirm={() => {
          setBusy(true);
          void engine
            .logoutProvider(id)
            .catch(() => undefined)
            .finally(() => {
              setBusy(false);
              setConfirmOut(false);
              onChanged();
            });
        }}
        onCancel={() => setConfirmOut(false)}
      />
    </>
  );
}
