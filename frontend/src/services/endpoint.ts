/**
 * Découverte de l'endpoint du moteur IA.
 *
 * - Dans l'app Tauri : commande IPC `get_engine_endpoint` → { port, token }
 *   (ARCHITECTURE.md §5). Détection via `window.__TAURI_INTERNALS__` ; on
 *   tente d'abord l'API officielle `@tauri-apps/api/core` en import dynamique
 *   (ignoré par Vite), puis les internals en repli — l'app doit compiler et
 *   tourner dans un simple navigateur sans Tauri installé.
 * - En dev navigateur : variables d'env VITE_ENGINE_URL / VITE_ENGINE_TOKEN.
 */

export interface EngineEndpoint {
  baseUrl: string;
  token: string;
}

interface TauriInternals {
  invoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T>;
}

declare global {
  interface Window {
    __TAURI_INTERNALS__?: TauriInternals;
  }
}

export function isTauri(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.__TAURI_INTERNALS__ !== "undefined"
  );
}

interface EndpointPayload {
  port: number;
  token: string;
}

export async function tauriInvoke<T>(cmd: string): Promise<T> {
  try {
    // Import dynamique volontairement non résolu par Vite ni TypeScript :
    // le paquet n'est présent que dans le contexte Tauri.
    const specifier = "@tauri-apps/api/core";
    const mod = (await import(/* @vite-ignore */ specifier)) as {
      invoke<R>(command: string): Promise<R>;
    };
    return await mod.invoke<T>(cmd);
  } catch {
    const internals = window.__TAURI_INTERNALS__;
    if (!internals) {
      throw new Error("Contexte Tauri indisponible.");
    }
    return internals.invoke<T>(cmd);
  }
}

async function resolveEndpoint(): Promise<EngineEndpoint> {
  if (isTauri()) {
    const { port, token } = await tauriInvoke<EndpointPayload>(
      "get_engine_endpoint",
    );
    return { baseUrl: `http://127.0.0.1:${port}`, token };
  }
  const env = import.meta.env;
  const baseUrl = (env.VITE_ENGINE_URL ?? "http://127.0.0.1:8765").replace(
    /\/+$/,
    "",
  );
  return { baseUrl, token: env.VITE_ENGINE_TOKEN ?? "" };
}

let cached: Promise<EngineEndpoint> | null = null;

/** Endpoint mémoïsé ; une résolution en échec n'est pas mise en cache. */
export function getEngineEndpoint(): Promise<EngineEndpoint> {
  if (cached === null) {
    cached = resolveEndpoint().catch((err: unknown) => {
      cached = null;
      throw err;
    });
  }
  return cached;
}
