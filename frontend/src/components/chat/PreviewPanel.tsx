import { useCallback, useEffect, useRef, useState } from "react";
import { useT } from "../../i18n";
import type { MessageKey } from "../../i18n/dictionaries";
import type { Tone } from "../../lib/labels";
import { engine, EngineError, toHumanMessage } from "../../services/engine";
import { pickDirectory } from "../../services/endpoint";
import type { PreviewInfo, PreviewState } from "../../types/engine";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { Spinner } from "../ui/Spinner";

const TONES: Record<PreviewState, Tone> = {
  stopped: "muted",
  deps_missing: "info",
  installing: "info",
  starting: "info",
  ready: "ok",
  compiling: "info",
  compile_error: "danger",
  unreachable: "danger",
  stopping: "muted",
  failed: "danger",
};
const TRANSITIONAL = new Set<PreviewState>([
  "installing",
  "starting",
  "compiling",
  "stopping",
]);
const MANUAL_FRAMEWORKS = [
  "vite",
  "next",
  "nuxt",
  "astro",
  "sveltekit",
  "angular",
  "vue-cli",
  "cra",
  "static",
];

/**
 * Isolation : la page prévisualisée vit sur une autre origine (127.0.0.1:port)
 * que l'application ; elle n'a ni le jeton du moteur ni accès à Tauri. Le
 * bac à sable retire en plus la navigation du cadre parent, le téléchargement
 * et les API de fenêtre de premier niveau.
 */
const SANDBOX = "allow-scripts allow-forms allow-same-origin allow-popups allow-modals";

export function PreviewPanel({ projectId }: { projectId: string }) {
  const t = useT();
  const [info, setInfo] = useState<PreviewInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [trust, setTrust] = useState(false);
  const [path, setPath] = useState("");
  const [nonce, setNonce] = useState(0);
  const autoStarted = useRef(false);

  const refresh = useCallback(() => {
    return engine
      .getPreview(projectId)
      .then((next) => {
        setInfo(next);
        return next;
      })
      .catch((err: unknown) => {
        setError(toHumanMessage(err));
        return null;
      });
  }, [projectId]);

  // Suivi de l'état réel : rapide pendant les transitions, lent sinon.
  useEffect(() => {
    autoStarted.current = false;
    setInfo(null);
    setError(null);
    void refresh();
  }, [projectId, refresh]);
  const state = info?.state ?? "stopped";
  const configured = info?.configured === true;
  useEffect(() => {
    if (!configured) return;
    const delay = TRANSITIONAL.has(state) ? 800 : 3000;
    const timer = window.setInterval(() => void refresh(), delay);
    return () => window.clearInterval(timer);
  }, [configured, state, refresh]);

  const act = useCallback(
    async (job: () => Promise<PreviewInfo>) => {
      setBusy(true);
      setError(null);
      try {
        setInfo(await job());
      } catch (err) {
        setError(err instanceof EngineError ? err.humanMessage : toHumanMessage(err));
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  const configure = (root: string, extra?: { subdir?: string; framework?: string }) =>
    act(() => engine.configurePreview(projectId, { root_path: root, ...extra }));
  const start = (installDeps = false) =>
    act(() => engine.startPreview(projectId, { trust, install_deps: installDeps }));

  // Automatique : un dossier déjà approuvé redémarre seul à l'ouverture du panneau.
  useEffect(() => {
    if (
      info !== null &&
      info.configured &&
      info.state === "stopped" &&
      info.runnable === true &&
      info.needs_trust === false &&
      !autoStarted.current
    ) {
      autoStarted.current = true;
      void act(() => engine.startPreview(projectId, {}));
    }
  }, [info, projectId, act]);

  const choose = async () => {
    const picked = await pickDirectory();
    if (picked !== null) await configure(picked);
  };

  const label = t(`preview.state.${state}` as MessageKey);
  const live = state === "ready" || state === "compiling" || state === "compile_error";
  const running = live || TRANSITIONAL.has(state) || state === "unreachable";

  return (
    <aside
      aria-label={t("preview.title")}
      className="flex w-[46%] min-w-[340px] max-w-[900px] shrink-0 flex-col border-l border-rule bg-paper"
    >
      <header className="flex h-12 shrink-0 items-center gap-2 border-b border-rule px-3">
        <h2 className="text-sm font-medium text-ink">{t("preview.title")}</h2>
        <Badge tone={TONES[state]} live={TRANSITIONAL.has(state)}>
          {label}
        </Badge>
        {info?.url !== undefined && info.url !== null && (
          <span className="min-w-0 truncate font-mono text-xs text-muted" title={info.url}>
            {info.url}
          </span>
        )}
        {info?.port !== undefined && info.port !== null && (
          <span className="shrink-0 text-xs text-neutral">
            {t("preview.port", { port: info.port })}
          </span>
        )}
        <div className="ml-auto flex shrink-0 items-center gap-1">
          {live && (
            <>
              <Button className="h-7 px-2" onClick={() => setNonce((n) => n + 1)}>
                {t("preview.refresh")}
              </Button>
              <Button
                className="h-7 px-2"
                onClick={() => {
                  void engine
                    .openPreviewExternal(projectId)
                    .catch((err: unknown) => setError(toHumanMessage(err)));
                }}
              >
                {t("preview.external")}
              </Button>
            </>
          )}
          {running && (
            <Button
              className="h-7 px-2"
              loading={busy}
              onClick={() => void act(() => engine.stopPreview(projectId))}
            >
              {t("preview.stop")}
            </Button>
          )}
        </div>
      </header>

      {error !== null && (
        <p role="alert" className="border-b border-danger/40 px-4 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      {state === "compile_error" && info?.error != null && (
        <div role="alert" className="max-h-32 shrink-0 overflow-auto border-b border-danger/40 bg-danger/5 px-4 py-2">
          <p className="text-xs font-medium text-danger">{t("preview.error.compile")}</p>
          <pre className="mt-1 whitespace-pre-wrap font-mono text-xs text-ink">{info.error}</pre>
        </div>
      )}

      <div className="relative min-h-0 flex-1">
        {live && info?.url != null ? (
          // Fond blanc explicite : sans lui, une page sans arrière-plan hérite
          // du thème sombre de l'application et paraît « toute noire ».
          <iframe
            key={nonce}
            title={t("preview.title")}
            src={info.url}
            sandbox={SANDBOX}
            referrerPolicy="no-referrer"
            className="absolute inset-0 size-full border-0 bg-white"
          />
        ) : (
          <div className="h-full overflow-auto px-5 py-6">
            <Body
              info={info}
              state={state}
              busy={busy}
              trust={trust}
              path={path}
              setTrust={setTrust}
              setPath={setPath}
              onChoose={() => void choose()}
              onConfigure={(root, extra) => void configure(root, extra)}
              onStart={start}
              onRestart={() => void act(() => engine.restartPreview(projectId))}
            />
          </div>
        )}
      </div>

      {info?.logs !== undefined && info.logs.length > 0 && (
        <details className="shrink-0 border-t border-rule px-4 py-2">
          <summary className="cursor-pointer text-xs text-muted">{t("preview.logs")}</summary>
          <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap font-mono text-xs text-neutral">
            {info.logs.slice(-40).join("\n")}
          </pre>
        </details>
      )}
    </aside>
  );
}

interface BodyProps {
  info: PreviewInfo | null;
  state: PreviewState;
  busy: boolean;
  trust: boolean;
  path: string;
  setTrust: (value: boolean) => void;
  setPath: (value: string) => void;
  onChoose: () => void;
  onConfigure: (root: string, extra?: { subdir?: string; framework?: string }) => void;
  onStart: (installDeps?: boolean) => void;
  onRestart: () => void;
}

function Body(p: BodyProps) {
  const t = useT();
  const { info, state } = p;

  if (info === null) {
    return (
      <div className="flex items-center gap-3 text-sm text-neutral" role="status">
        <Spinner /> {t("preview.starting")}
      </div>
    );
  }

  if (!info.configured) {
    return (
      <div className="flex max-w-md flex-col gap-3">
        <h3 className="text-base text-ink">{t("preview.pick.title")}</h3>
        <p className="text-sm text-muted">{t("preview.pick.body")}</p>
        <div>
          <Button variant="primary" onClick={p.onChoose} loading={p.busy}>
            {t("preview.pick.button")}
          </Button>
        </div>
        <div className="flex gap-2">
          <input
            value={p.path}
            onChange={(e) => p.setPath(e.target.value)}
            placeholder={t("preview.path.placeholder")}
            aria-label={t("preview.path.placeholder")}
            className="min-w-0 flex-1 rounded-md border border-rule bg-paper px-3 py-1.5 text-sm text-ink"
          />
          <Button disabled={p.path.trim().length === 0} onClick={() => p.onConfigure(p.path.trim())}>
            {t("preview.path.use")}
          </Button>
        </div>
      </div>
    );
  }

  const root = info.root_path ?? "";

  // Détection impossible : message explicite + configuration manuelle.
  if (info.detection_error != null && info.runnable !== true) {
    return (
      <div className="flex max-w-md flex-col gap-3">
        <p role="alert" className="text-sm text-danger">
          {t("preview.error.detect")} — {info.detection_error}
        </p>
        {info.candidates !== undefined && info.candidates.length > 1 && (
          <div className="flex flex-col gap-2">
            <p className="text-sm text-muted">{t("preview.choose.app")}</p>
            <div className="flex flex-wrap gap-2">
              {info.candidates.map((name) => (
                <Button key={name} onClick={() => p.onConfigure(root, { subdir: name })}>
                  {name}
                </Button>
              ))}
            </div>
          </div>
        )}
        <div className="flex flex-col gap-2">
          <p className="text-sm text-muted">{t("preview.choose.framework")}</p>
          <div className="flex flex-wrap gap-2">
            {MANUAL_FRAMEWORKS.map((id) => (
              <Button
                key={id}
                onClick={() =>
                  p.onConfigure(root, { framework: id, subdir: info.subdir ?? undefined })
                }
              >
                {id}
              </Button>
            ))}
          </div>
        </div>
        <div>
          <Button onClick={p.onChoose}>{t("preview.change")}</Button>
        </div>
      </div>
    );
  }

  if (state === "starting" || state === "installing" || state === "stopping") {
    return (
      <div className="flex items-center gap-3 text-sm text-neutral" role="status">
        <Spinner />
        {state === "installing" ? t("preview.installing") : t("preview.starting")}
      </div>
    );
  }

  const failure = state === "failed" || state === "unreachable";
  const canStart = state === "stopped" || state === "deps_missing" || failure;
  const needsInstall = info.deps_installed === false;

  return (
    <div className="flex max-w-md flex-col gap-3">
      {failure && (
        <p role="alert" className="text-sm text-danger">
          {state === "unreachable" ? t("preview.error.unreachable") : t("preview.error.failed")}
          {info.error ? ` — ${info.error}` : ""}
        </p>
      )}
      {state === "deps_missing" && <p className="text-sm text-muted">{t("preview.deps.missing")}</p>}
      <p className="text-sm text-ink">
        {t("preview.detected", { label: info.label ?? "—" })}
        <span className="text-neutral">
          {info.package_manager ? ` · ${t("preview.pm", { pm: info.package_manager })}` : ""}
          {info.hot_update ? ` · ${t(`preview.hot.${info.hot_update}` as MessageKey)}` : ""}
        </span>
      </p>
      <p className="truncate font-mono text-xs text-neutral" title={info.app_root ?? root}>
        {info.app_root ?? root}
      </p>
      {info.needs_trust === true && (
        <label className="flex items-start gap-2 text-sm text-muted">
          <input
            type="checkbox"
            checked={p.trust}
            onChange={(e) => p.setTrust(e.target.checked)}
            className="mt-0.5"
          />
          {t("preview.trust")}
        </label>
      )}
      {canStart && (
        <div className="flex flex-wrap gap-2">
          <Button
            variant="primary"
            loading={p.busy}
            disabled={info.needs_trust === true && !p.trust}
            onClick={() => (failure ? p.onRestart() : p.onStart(needsInstall))}
          >
            {needsInstall ? t("preview.install") : failure ? t("preview.restart") : t("preview.start")}
          </Button>
          <Button onClick={p.onChoose}>{t("preview.change")}</Button>
        </div>
      )}
    </div>
  );
}
