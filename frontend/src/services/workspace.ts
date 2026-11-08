/**
 * Écriture des changements acceptés, par le broker Rust (ADR-003).
 *
 * Le moteur n'écrit jamais dans un projet. Après la décision de l'utilisateur,
 * c'est la commande `fs_apply_change` qui contrôle le périmètre accordé, refuse
 * les fichiers protégés et vérifie que le fichier est toujours celui relu.
 */

import { isTauri, pickDirectory, tauriInvoke } from "./endpoint";
import type { FileChangeDetail } from "../types/engine";

export type ApplyFailure = "desktop_only" | "no_scope" | "conflict" | "denied" | "failed";

export class ApplyError extends Error {
  readonly reason: ApplyFailure;

  constructor(reason: ApplyFailure, message: string) {
    super(message);
    this.name = "ApplyError";
    this.reason = reason;
  }
}

/** Droits déjà accordés dans cette session : on ne redemande pas à chaque fichier. */
const granted = new Set<string>();

function brokerMessage(error: unknown): { kind: string; message: string } {
  if (typeof error === "object" && error !== null) {
    const record = error as { kind?: unknown; message?: unknown };
    return {
      kind: typeof record.kind === "string" ? record.kind : "",
      message: typeof record.message === "string" ? record.message : "",
    };
  }
  return { kind: "", message: String(error) };
}

function grant(projectId: string, root: string): Promise<string> {
  return tauriInvoke<string>("fs_scope_grant", { projectId, path: root, level: "development" });
}

/**
 * Le broker n'accorde un dossier que s'il vient du sélecteur natif de cette
 * session : sans ça (après un redémarrage), on le fait choisir une fois.
 */
async function ensureScope(projectId: string, root: string): Promise<void> {
  const key = `${projectId}\u0000${root}`;
  if (granted.has(key)) return;
  try {
    await grant(projectId, root);
  } catch {
    if ((await pickDirectory()) === null) {
      throw new ApplyError("no_scope", root);
    }
    try {
      await grant(projectId, root);
    } catch {
      throw new ApplyError("no_scope", root);
    }
  }
  granted.add(key);
}

/** Écrit un changement (`apply`) ou rétablit l'état d'origine (`revert`). */
export async function writeChange(
  projectId: string,
  root: string,
  change: FileChangeDetail,
  direction: "apply" | "revert",
): Promise<void> {
  if (!isTauri()) throw new ApplyError("desktop_only", "");
  await ensureScope(projectId, root);
  const applying = direction === "apply";
  try {
    await tauriInvoke<void>("fs_apply_change", {
      projectId,
      path: `${root.replace(/[\\/]+$/, "")}/${change.path}`,
      expectedSha256: applying ? change.base_sha256 : change.new_sha256,
      contents: applying ? change.new_content : change.base_content,
    });
  } catch (error) {
    const { kind, message } = brokerMessage(error);
    if (message.includes("conflict")) throw new ApplyError("conflict", message);
    if (kind === "permission_denied" || message.includes("protected")) {
      throw new ApplyError("denied", message);
    }
    throw new ApplyError("failed", message);
  }
}
