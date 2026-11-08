/** Diff par lignes pour la revue des fichiers proposés par les agents. */

export type DiffRow =
  | { kind: "same" | "add" | "del"; text: string }
  | { kind: "skip"; count: number };

/** Au-delà, le calcul gèlerait l'interface : on affiche les deux versions sans diff. */
const MAX_CELLS = 4_000_000;
const CONTEXT_LINES = 3;

function toLines(text: string | null): string[] {
  if (text === null || text.length === 0) return [];
  const lines = text.split(/\r?\n/);
  if (lines[lines.length - 1] === "") lines.pop();
  return lines;
}

function lcsRows(a: string[], b: string[]): DiffRow[] {
  const width = b.length + 1;
  const table = new Uint32Array((a.length + 1) * width);
  for (let i = a.length - 1; i >= 0; i -= 1) {
    for (let j = b.length - 1; j >= 0; j -= 1) {
      table[i * width + j] =
        a[i] === b[j]
          ? (table[(i + 1) * width + j + 1] ?? 0) + 1
          : Math.max(table[(i + 1) * width + j] ?? 0, table[i * width + j + 1] ?? 0);
    }
  }
  const rows: DiffRow[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length || j < b.length) {
    if (i < a.length && j < b.length && a[i] === b[j]) {
      rows.push({ kind: "same", text: a[i] ?? "" });
      i += 1;
      j += 1;
    } else if (
      j < b.length &&
      (i >= a.length || (table[i * width + j + 1] ?? 0) > (table[(i + 1) * width + j] ?? 0))
    ) {
      rows.push({ kind: "add", text: b[j] ?? "" });
      j += 1;
    } else {
      rows.push({ kind: "del", text: a[i] ?? "" });
      i += 1;
    }
  }
  return rows;
}

/** Diff complet, ou null si les fichiers sont trop grands pour être comparés. */
export function diffLines(before: string | null, after: string | null): DiffRow[] | null {
  const a = toLines(before);
  const b = toLines(after);
  let start = 0;
  while (start < a.length && start < b.length && a[start] === b[start]) start += 1;
  let endA = a.length;
  let endB = b.length;
  while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) {
    endA -= 1;
    endB -= 1;
  }
  const middleA = a.slice(start, endA);
  const middleB = b.slice(start, endB);
  if (middleA.length * middleB.length > MAX_CELLS) return null;
  return [
    ...a.slice(0, start).map((text): DiffRow => ({ kind: "same", text })),
    ...lcsRows(middleA, middleB),
    ...a.slice(endA).map((text): DiffRow => ({ kind: "same", text })),
  ];
}

/** Garde les changements et quelques lignes autour ; replie le reste. */
export function withContext(rows: DiffRow[], context = CONTEXT_LINES): DiffRow[] {
  const keep = new Array<boolean>(rows.length).fill(false);
  rows.forEach((row, index) => {
    if (row.kind === "same" || row.kind === "skip") return;
    const end = Math.min(rows.length - 1, index + context);
    for (let k = Math.max(0, index - context); k <= end; k += 1) keep[k] = true;
  });
  const out: DiffRow[] = [];
  let skipped = 0;
  rows.forEach((row, index) => {
    if (keep[index] === true) {
      if (skipped > 0) out.push({ kind: "skip", count: skipped });
      skipped = 0;
      out.push(row);
    } else {
      skipped += 1;
    }
  });
  if (skipped > 0) out.push({ kind: "skip", count: skipped });
  return out;
}

const MACHINE_BLOCK =
  /<elysium-(file|tool)\b[\s\S]*?(<\/elysium-\1>|$)|<elysium-delete\b[^>]*>/g;

/** Retire du texte en flux les blocs destinés au moteur (fichiers, appels d'outils). */
export function hideMachineBlocks(text: string): string {
  return text.includes("<elysium-") ? text.replace(MACHINE_BLOCK, "").trimEnd() : text;
}
