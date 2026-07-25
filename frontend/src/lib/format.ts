/** Normalise une progression exprimée en 0–1 ou 0–100 vers 0–1. */
export function normalizeProgress(value: number | null | undefined): number | null {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return null;
  }
  const scaled = value > 1 ? value / 100 : value;
  return Math.min(1, Math.max(0, scaled));
}

/** Fenêtre de contexte en tokens → « 200K », « 1M »… ou null. */
export function formatContextWindow(
  tokens: number | null | undefined,
): string | null {
  if (tokens === null || tokens === undefined || !Number.isFinite(tokens)) {
    return null;
  }
  if (tokens <= 0) return null;
  if (tokens >= 1_000_000) {
    const millions = tokens / 1_000_000;
    return `${Number.isInteger(millions) ? String(millions) : millions.toFixed(1)}M`;
  }
  if (tokens >= 1_000) return `${String(Math.round(tokens / 1_000))}K`;
  return String(tokens);
}

/** Palier de coût 1–4 → « $ » à « $$$$ », ou null. */
export function costTierLabel(tier: number | null | undefined): string | null {
  if (tier === null || tier === undefined || !Number.isFinite(tier)) {
    return null;
  }
  const clamped = Math.min(4, Math.max(1, Math.round(tier)));
  return "$".repeat(clamped);
}

/** Année d'une date ISO, ou null si absente/illisible. */
export function releaseYear(iso: string | null | undefined): string | null {
  if (iso === null || iso === undefined || iso.length === 0) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return String(date.getFullYear());
}

/** Date courte en français, ou null si absente/illisible. */
export function formatDate(iso: string | undefined): string | null {
  if (iso === undefined) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleDateString("fr-FR", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}
