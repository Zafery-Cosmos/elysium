import { useEffect, useState } from "react";
import { isTauri, tauriInvoke } from "../../services/endpoint";

interface EngineStatusReport {
  state: "starting" | "running" | "failed" | "stopped";
  port: number;
  restarts: number;
  last_stderr: string[];
}

const STATE_LABEL: Record<EngineStatusReport["state"], string> = {
  starting: "démarrage en cours",
  running: "en ligne",
  failed: "en échec",
  stopped: "arrêté",
};

/**
 * Détails techniques du sidecar moteur (état + dernières lignes stderr),
 * disponibles uniquement dans l'app Tauri via la commande `engine_status`.
 * Ne rend rien en mode navigateur.
 */
export function EngineDiagnostics() {
  const [report, setReport] = useState<EngineStatusReport | null>(null);

  useEffect(() => {
    if (!isTauri()) return;
    let cancelled = false;
    const poll = (): void => {
      tauriInvoke<EngineStatusReport>("engine_status")
        .then((r) => {
          if (!cancelled) setReport(r);
        })
        .catch(() => {
          // IPC indisponible : rien à afficher.
        });
    };
    poll();
    const timer = window.setInterval(poll, 3_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  if (report === null) return null;

  return (
    <div className="w-full text-xs text-muted">
      <p>
        Moteur : {STATE_LABEL[report.state]} · port {report.port} ·{" "}
        {report.restarts} redémarrage{report.restarts > 1 ? "s" : ""}
      </p>
      {report.last_stderr.length > 0 && (
        <pre className="mt-1.5 max-h-40 overflow-auto rounded-md bg-paper-3 p-2.5 font-mono text-[11px] leading-relaxed whitespace-pre-wrap text-ink">
          {report.last_stderr.join("\n")}
        </pre>
      )}
    </div>
  );
}
