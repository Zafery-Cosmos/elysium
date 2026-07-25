import { useEffect, useState } from "react";
import { isTauri } from "../services/endpoint";

/**
 * Mise à jour intégrée : au démarrage (dans l'app Tauri uniquement), vérifie
 * s'il existe une nouvelle version signée sur GitHub Releases et propose de
 * l'installer sans quitter l'app. Aucun effet en mode navigateur.
 *
 * Le flux Tauri (check → downloadAndInstall → relaunch) est chargé en import
 * dynamique pour que l'app compile et tourne sans les plugins hors Tauri.
 */
type Phase = "idle" | "available" | "downloading" | "done" | "error";

interface UpdateInfo {
  version: string;
  notes?: string;
  install: (onProgress: (done: number, total: number | null) => void) => Promise<void>;
}

export function UpdatePrompt() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [info, setInfo] = useState<UpdateInfo | null>(null);
  const [pct, setPct] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    if (!isTauri()) return;
    let cancelled = false;
    void (async () => {
      try {
        const { check } = await import("@tauri-apps/plugin-updater");
        const update = await check();
        if (cancelled || update === null) return;
        setInfo({
          version: update.version,
          notes: update.body,
          install: async (onProgress) => {
            let downloaded = 0;
            await update.downloadAndInstall((event) => {
              if (event.event === "Started") {
                onProgress(0, event.data.contentLength ?? null);
              } else if (event.event === "Progress") {
                downloaded += event.data.chunkLength;
                onProgress(downloaded, null);
              }
            });
          },
        });
        setPhase("available");
      } catch {
        // Pas de réseau / pas de release : on reste silencieux.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const start = async (): Promise<void> => {
    if (info === null) return;
    setPhase("downloading");
    setError(null);
    try {
      let total: number | null = null;
      await info.install((done, t) => {
        if (t !== null) total = t;
        setPct(total !== null && total > 0 ? Math.round((done / total) * 100) : null);
      });
      setPhase("done");
      const { relaunch } = await import("@tauri-apps/plugin-process");
      await relaunch();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setPhase("error");
    }
  };

  if (phase === "idle" || dismissed) return null;

  return (
    <div
      role="dialog"
      aria-label="Mise à jour disponible"
      className="fixed bottom-4 right-4 z-50 w-80 animate-rise-in rounded-xl border border-rule bg-paper p-4 shadow-lg"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="grid size-6 place-items-center rounded-md bg-chip">
            <img src="/logo.png" alt="" className="size-5" />
          </span>
          <p className="text-sm font-semibold text-ink">Mise à jour disponible</p>
        </div>
        {phase !== "downloading" && phase !== "done" && (
          <button
            type="button"
            onClick={() => setDismissed(true)}
            aria-label="Plus tard"
            className="rounded-sm text-neutral hover:text-ink"
          >
            ✕
          </button>
        )}
      </div>

      {phase === "available" && info !== null && (
        <>
          <p className="mt-2 text-xs text-muted">
            Elysium {info.version} est prête à être installée.
          </p>
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              onClick={() => void start()}
              className="h-8 flex-1 rounded-md bg-ink px-3 text-xs font-medium text-paper transition-transform active:translate-y-px hover:bg-ink/85"
            >
              Installer et redémarrer
            </button>
            <button
              type="button"
              onClick={() => setDismissed(true)}
              className="h-8 rounded-md border border-rule px-3 text-xs text-muted hover:text-ink"
            >
              Plus tard
            </button>
          </div>
        </>
      )}

      {phase === "downloading" && (
        <div className="mt-3">
          <p className="text-xs text-muted">
            Téléchargement{pct !== null ? ` — ${pct}%` : "…"}
          </p>
          <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-paper-3">
            <div
              className="h-full bg-ink transition-[width] duration-200"
              style={{ width: pct !== null ? `${pct}%` : "40%" }}
            />
          </div>
        </div>
      )}

      {phase === "done" && (
        <p className="mt-2 text-xs text-muted">Installation terminée, redémarrage…</p>
      )}

      {phase === "error" && (
        <>
          <p className="mt-2 text-xs text-danger">
            Échec de la mise à jour{error !== null ? ` : ${error}` : "."}
          </p>
          <button
            type="button"
            onClick={() => setPhase("available")}
            className="mt-2 rounded-sm text-xs text-muted underline underline-offset-2 hover:text-ink"
          >
            Réessayer
          </button>
        </>
      )}
    </div>
  );
}
