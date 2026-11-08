import { useCallback, useEffect, useState } from "react";
import { engine, toHumanMessage } from "../../services/engine";
import { isTauri } from "../../services/endpoint";
import { useT } from "../../i18n";
import { Button } from "../ui/Button";
import { Input } from "../ui/Input";
import type { DatabaseInfo } from "../../types/engine";

type Status = { tone: "ok" | "error"; text: string } | null;

/** Choix de la base : SQLite locale, ou un serveur PostgreSQL. */
export function DatabasePanel() {
  const t = useT();
  const [info, setInfo] = useState<DatabaseInfo | null>(null);
  const [url, setUrl] = useState("");
  const [copy, setCopy] = useState(true);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<Status>(null);
  const [restart, setRestart] = useState(false);

  const load = useCallback(() => {
    engine.getDatabase().then(setInfo).catch((err: unknown) => {
      setStatus({ tone: "error", text: toHumanMessage(err) });
    });
  }, []);

  useEffect(load, [load]);

  const run = async (action: () => Promise<Status>): Promise<void> => {
    setBusy(true);
    setStatus(null);
    try {
      setStatus(await action());
    } catch (err) {
      setStatus({ tone: "error", text: toHumanMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  const test = (): Promise<void> =>
    run(async () => {
      const { version } = await engine.testDatabase(url.trim());
      return { tone: "ok", text: t("database.testOk", { version }) };
    });

  const save = (): Promise<void> =>
    run(async () => {
      const { copied_rows: count } = await engine.saveDatabase(url.trim(), copy);
      setUrl(""); // le mot de passe ne reste pas à l'écran
      setRestart(true);
      load();
      return { tone: "ok", text: t("database.saved", { count }) };
    });

  const forget = (): Promise<void> =>
    run(async () => {
      await engine.forgetDatabase();
      setRestart(true);
      load();
      return { tone: "ok", text: t("database.forgotten") };
    });

  const relaunch = async (): Promise<void> => {
    const { relaunch: restartApp } = await import("@tauri-apps/plugin-process");
    await restartApp();
  };

  const disabled = busy || url.trim().length === 0;

  return (
    <div>
      <h2 className="text-md">{t("database.title")}</h2>
      <p className="mt-1 text-sm text-neutral">{t("database.intro")}</p>

      {info !== null && (
        <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
          <dt className="text-neutral">{t("database.current")}</dt>
          <dd className="text-ink">{info.backend === "sqlite" ? t("database.sqlite") : "PostgreSQL"}</dd>
          <dt className="text-neutral">{t("database.location")}</dt>
          <dd className="break-all font-mono text-xs text-ink">{info.location}</dd>
        </dl>
      )}
      {info?.fallback_error !== null && info?.fallback_error !== undefined && (
        <p role="alert" className="mt-3 rounded-md border border-danger/40 px-3 py-2 text-sm text-danger">
          {t("database.fallback", { reason: info.fallback_error })}
        </p>
      )}

      <div className="mt-5 flex flex-col gap-3">
        <label className="flex flex-col gap-1.5 text-sm text-ink">
          {t("database.url")}
          <Input
            type="password"
            autoComplete="off"
            spellCheck={false}
            placeholder="postgresql://user:password@host:5432/elysium"
            value={url}
            onChange={(e) => {
              setUrl(e.target.value);
            }}
          />
        </label>
        <label className="flex items-center gap-2 text-sm text-muted">
          <input
            type="checkbox"
            checked={copy}
            onChange={(e) => {
              setCopy(e.target.checked);
            }}
          />
          {t("database.copy")}
        </label>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="ghost"
            disabled={disabled}
            onClick={() => {
              void test();
            }}
          >
            {t("database.test")}
          </Button>
          <Button
            variant="primary"
            disabled={disabled}
            onClick={() => {
              void save();
            }}
          >
            {t("database.save")}
          </Button>
          {info?.configured !== null && info?.configured !== undefined && (
            <Button
              variant="ghost"
              disabled={busy}
              onClick={() => {
                void forget();
              }}
            >
              {t("database.useLocal")}
            </Button>
          )}
        </div>
      </div>

      {status !== null && (
        <p
          role={status.tone === "error" ? "alert" : "status"}
          className={status.tone === "error" ? "mt-3 text-sm text-danger" : "mt-3 text-sm text-ink"}
        >
          {status.text}
        </p>
      )}
      {restart && (
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <p className="text-sm text-muted">{t("database.restart")}</p>
          {isTauri() && (
            <Button
              variant="primary"
              onClick={() => {
                void relaunch();
              }}
            >
              {t("database.restartNow")}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
