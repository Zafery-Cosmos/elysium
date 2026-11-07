/**
 * Small force-directed layout for the project memory map (no dependency).
 *
 * - repulsion between nearby nodes (spatial grid, so 600 nodes stay cheap),
 * - springs along the edges (files that import each other end up close),
 * - a weak pull to the centre so unconnected files do not drift away.
 *
 * Everything here is deterministic (no Math.random): the same project always starts
 * from the same layout, which keeps the map stable between visits and the tests exact.
 */

export interface GraphNodeIn {
  id: string;
  degree: number;
}
export interface GraphEdgeIn {
  source: string;
  target: string;
}

export interface SimNode {
  id: string;
  index: number;
  x: number;
  y: number;
  vx: number;
  vy: number;
  r: number;
  degree: number;
  /** Held in place (while the user drags it). */
  pinned: boolean;
}

export interface SimLink {
  a: number;
  b: number;
}

export interface View {
  x: number;
  y: number;
  k: number;
}

const CELL = 150;
const REPEL = 150;
const LINK_REST = 40;
const LINK_STRENGTH = 0.3;
const GRAVITY = 0.012;
/** Files with no link at all are pulled in harder, otherwise they float far away and shrink the map. */
const LONELY_GRAVITY = 7;
const DAMPING = 0.62;
const MAX_SPEED = 28;

export function radiusFor(degree: number): number {
  return 3 + Math.min(11, Math.sqrt(Math.max(0, degree)) * 2.2);
}

export class ForceSim {
  readonly nodes: SimNode[];
  readonly links: SimLink[];
  /** For each node index, the indexes it is linked to (either direction). */
  readonly neighbors: Array<Set<number>>;
  alpha = 1;

  constructor(nodes: GraphNodeIn[], edges: GraphEdgeIn[]) {
    const index = new Map<string, number>();
    this.nodes = nodes.map((n, i) => {
      index.set(n.id, i);
      const angle = i * 2.399963; // golden angle: an even spiral, deterministic
      const dist = 16 * Math.sqrt(i + 1);
      return {
        id: n.id,
        index: i,
        x: Math.cos(angle) * dist,
        y: Math.sin(angle) * dist,
        vx: 0,
        vy: 0,
        r: radiusFor(n.degree),
        degree: n.degree,
        pinned: false,
      };
    });
    this.neighbors = this.nodes.map(() => new Set<number>());
    const seen = new Set<string>();
    this.links = [];
    for (const e of edges) {
      const a = index.get(e.source);
      const b = index.get(e.target);
      if (a === undefined || b === undefined || a === b) continue;
      const key = a < b ? `${String(a)}:${String(b)}` : `${String(b)}:${String(a)}`;
      if (seen.has(key)) continue;
      seen.add(key);
      this.links.push({ a, b });
      this.neighbors[a]?.add(b);
      this.neighbors[b]?.add(a);
    }
  }

  get settled(): boolean {
    return this.alpha < 0.01;
  }

  /** Wake the simulation up (after a drag, or when the data changes). */
  reheat(alpha = 0.5): void {
    this.alpha = Math.max(this.alpha, alpha);
  }

  /** One step. Returns the remaining energy. */
  tick(): number {
    const a = this.alpha;
    if (a < 0.002) return a;
    const nodes = this.nodes;

    // 1. repulsion, only between nodes in the same or neighbouring grid cells
    const grid = new Map<number, number[]>();
    const keyOf = (cx: number, cy: number) => (cx + 2048) * 4096 + (cy + 2048);
    for (const n of nodes) {
      const key = keyOf(Math.floor(n.x / CELL), Math.floor(n.y / CELL));
      const bucket = grid.get(key);
      if (bucket) bucket.push(n.index);
      else grid.set(key, [n.index]);
    }
    for (const n of nodes) {
      const cx = Math.floor(n.x / CELL);
      const cy = Math.floor(n.y / CELL);
      for (let gx = cx - 1; gx <= cx + 1; gx++) {
        for (let gy = cy - 1; gy <= cy + 1; gy++) {
          const bucket = grid.get(keyOf(gx, gy));
          if (!bucket) continue;
          for (const j of bucket) {
            if (j <= n.index) continue; // each pair once
            const m = nodes[j];
            if (!m) continue;
            let dx = n.x - m.x;
            let dy = n.y - m.y;
            if (dx === 0 && dy === 0) {
              dx = (n.index - j) * 0.01;
              dy = 0.01;
            }
            const d = Math.max(Math.hypot(dx, dy), 6);
            const f = ((REPEL + (n.r + m.r) * 2) * a) / d;
            const fx = (dx / d) * f;
            const fy = (dy / d) * f;
            n.vx += fx;
            n.vy += fy;
            m.vx -= fx;
            m.vy -= fy;
          }
        }
      }
    }

    // 2. springs along the edges
    for (const l of this.links) {
      const s = nodes[l.a];
      const t = nodes[l.b];
      if (!s || !t) continue;
      const dx = t.x - s.x;
      const dy = t.y - s.y;
      const d = Math.max(Math.hypot(dx, dy), 0.01);
      const rest = LINK_REST + s.r + t.r;
      // a hub with 30 links must not be dragged by every one of them as hard as a leaf is by its only one
      const f = ((d - rest) * LINK_STRENGTH * a) / Math.pow(Math.max(1, Math.min(s.degree, t.degree)), 0.6);
      const fx = (dx / d) * f;
      const fy = (dy / d) * f;
      s.vx += fx;
      s.vy += fy;
      t.vx -= fx;
      t.vy -= fy;
    }

    // 3. gravity + integration
    for (const n of nodes) {
      const g = GRAVITY * (n.degree === 0 ? LONELY_GRAVITY : 1) * a;
      n.vx -= n.x * g;
      n.vy -= n.y * g;
      n.vx = Math.max(-MAX_SPEED, Math.min(MAX_SPEED, n.vx * DAMPING));
      n.vy = Math.max(-MAX_SPEED, Math.min(MAX_SPEED, n.vy * DAMPING));
      if (n.pinned) {
        n.vx = 0;
        n.vy = 0;
      } else {
        n.x += n.vx;
        n.y += n.vy;
      }
    }

    this.alpha = a * 0.985;
    return this.alpha;
  }

  /** Run until calm (used for the first layout, so the map does not "boil" on screen). */
  settle(maxTicks = 300): void {
    for (let i = 0; i < maxTicks && !this.settled; i++) this.tick();
  }
}

/* ————— view helpers ————— */

export function screenToWorld(view: View, sx: number, sy: number): { x: number; y: number } {
  return { x: (sx - view.x) / view.k, y: (sy - view.y) / view.k };
}

/** The node under a screen point (the last drawn = the one on top wins), or -1. */
export function pickNode(
  nodes: SimNode[],
  view: View,
  sx: number,
  sy: number,
  visible: (n: SimNode) => boolean = () => true,
): number {
  const p = screenToWorld(view, sx, sy);
  const slack = 4 / view.k;
  for (let i = nodes.length - 1; i >= 0; i--) {
    const n = nodes[i];
    if (!n || !visible(n)) continue;
    const reach = n.r + slack;
    if ((n.x - p.x) ** 2 + (n.y - p.y) ** 2 <= reach * reach) return i;
  }
  return -1;
}

/** A view that shows every visible node inside width × height. */
export function fitView(nodes: SimNode[], width: number, height: number, pad = 48, visible: (n: SimNode) => boolean = () => true): View {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const n of nodes) {
    if (!visible(n)) continue;
    minX = Math.min(minX, n.x - n.r);
    maxX = Math.max(maxX, n.x + n.r);
    minY = Math.min(minY, n.y - n.r);
    maxY = Math.max(maxY, n.y + n.r);
  }
  if (!Number.isFinite(minX) || width <= 0 || height <= 0) return { x: width / 2, y: height / 2, k: 1 };
  const w = Math.max(maxX - minX, 1);
  const h = Math.max(maxY - minY, 1);
  const k = Math.max(0.1, Math.min(2.2, Math.min((width - pad * 2) / w, (height - pad * 2) / h)));
  return { k, x: width / 2 - ((minX + maxX) / 2) * k, y: height / 2 - ((minY + maxY) / 2) * k };
}

/* ————— colours ————— */

const LANGUAGE_COLORS: Record<string, string> = {
  TypeScript: "#4f9cf7",
  JavaScript: "#f5d94a",
  Python: "#5fb3e6",
  Rust: "#f0a077",
  Go: "#5ed3d9",
  Java: "#f59a5b",
  Kotlin: "#b58cf7",
  Swift: "#ff7a59",
  CSS: "#c084fc",
  HTML: "#ff6b4a",
  Markdown: "#a3a3b3",
  JSON: "#9be15d",
  YAML: "#f472b6",
  TOML: "#fbbf24",
  SQL: "#34d399",
  Shell: "#86efac",
};

/** A stable colour for a language: known ones are fixed, others come from a hash. */
export function languageColor(language: string | null): string {
  if (language === null || language === "") return "#8b8b9c";
  const known = LANGUAGE_COLORS[language];
  if (known !== undefined) return known;
  let h = 0;
  for (let i = 0; i < language.length; i++) h = (h * 31 + language.charCodeAt(i)) % 360;
  return `hsl(${String(h)} 70% 66%)`;
}
