import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useT } from "../../i18n";
import { ForceSim, fitView, languageColor, pickNode, screenToWorld, type View } from "../../lib/forceLayout";
import type { MemoryGraphNode } from "../../types/engine";

interface Props {
  nodes: MemoryGraphNode[];
  edges: Array<{ source: string; target: string }>;
  selected: string | null;
  /** Free-text filter: matching files stay lit, the others fade. */
  query: string;
  onSelect: (path: string) => void;
}

type Drag =
  | { kind: "node"; index: number; startX: number; startY: number; moved: boolean }
  | { kind: "pan"; lastX: number; lastY: number; startX: number; startY: number; moved: boolean };

const MIN_ZOOM = 0.1;
const MAX_ZOOM = 4;
const base = (path: string) => path.slice(path.lastIndexOf("/") + 1);

/**
 * The project's file map: every file is a dot, every import a line.
 * Pure canvas + a small force simulation (see lib/forceLayout) — no graph library.
 * The list view next to it is the keyboard / screen-reader way to browse the same data.
 */
export function ForceGraph({ nodes, edges, selected, query, onSelect }: Props) {
  const t = useT();
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const simRef = useRef<ForceSim | null>(null);
  const colorsRef = useRef<string[]>([]);
  const hubsRef = useRef<Set<number>>(new Set());
  const viewRef = useRef<View>({ x: 0, y: 0, k: 1 });
  const sizeRef = useRef({ w: 800, h: 520 });
  const hoverRef = useRef(-1);
  const dragRef = useRef<Drag | null>(null);
  const rafRef = useRef(0);
  const pausedRef = useRef(false);
  const hiddenRef = useRef<Set<string>>(new Set());
  const selectedRef = useRef<string | null>(selected);
  const queryRef = useRef(query);
  const nodesRef = useRef(nodes);
  nodesRef.current = nodes;

  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [paused, setPaused] = useState(false);
  const [tip, setTip] = useState<{ x: number; y: number; node: MemoryGraphNode } | null>(null);

  const langOf = useCallback((index: number): string => nodesRef.current[index]?.language ?? "—", []);
  const visibleNode = useCallback((n: { index: number }) => !hiddenRef.current.has(langOf(n.index)), [langOf]);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const sim = simRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !sim || !ctx) return;
    const { w, h } = sizeRef.current;
    const dpr = window.devicePixelRatio || 1;
    const v = viewRef.current;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.translate(v.x, v.y);
    ctx.scale(v.k, v.k);

    const visible = (i: number) => !hiddenRef.current.has(langOf(i));
    const selectedIndex = selectedRef.current === null ? -1 : sim.nodes.findIndex((n) => n.id === selectedRef.current);
    const focus = hoverRef.current >= 0 ? hoverRef.current : selectedIndex;
    const around = focus >= 0 ? sim.neighbors[focus] : undefined;
    const q = queryRef.current.trim().toLowerCase();

    ctx.lineWidth = 1 / v.k;
    for (const l of sim.links) {
      if (!visible(l.a) || !visible(l.b)) continue;
      const a = sim.nodes[l.a];
      const b = sim.nodes[l.b];
      if (!a || !b) continue;
      const hot = focus >= 0 && (l.a === focus || l.b === focus);
      ctx.strokeStyle = hot ? "rgba(255,255,255,0.9)" : focus >= 0 ? "rgba(160,170,200,0.06)" : "rgba(160,170,200,0.24)";
      ctx.lineWidth = (hot ? 1.8 : 1) / v.k;
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
    }

    const faded = (n: { index: number; id: string }) =>
      (focus >= 0 && n.index !== focus && !(around?.has(n.index) ?? false)) || (q !== "" && !n.id.toLowerCase().includes(q));

    for (const n of sim.nodes) {
      if (!visible(n.index)) continue;
      const dim = faded(n);
      ctx.globalAlpha = dim ? 0.16 : 1;
      const color = colorsRef.current[n.index] ?? "#8b8b9c";
      ctx.fillStyle = color;
      if (!dim) {
        ctx.shadowColor = color;
        ctx.shadowBlur = n.index === focus ? 20 : 8;
      }
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;
      if (n.index === selectedIndex) {
        ctx.strokeStyle = "#ffffff";
        ctx.lineWidth = 2 / v.k;
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r + 3 / v.k, 0, Math.PI * 2);
        ctx.stroke();
      }
    }

    ctx.font = `${String(11 / v.k)}px "Geist Variable", ui-sans-serif, system-ui, sans-serif`;
    ctx.textAlign = "center";
    // Labels: what you point at first, then the best-connected files; a label that would
    // cover one already drawn is skipped, so the map stays readable (zoom in to see more).
    const wanted: Array<{ n: (typeof sim.nodes)[number]; rank: number }> = [];
    for (const n of sim.nodes) {
      if (!visible(n.index)) continue;
      const isFocus = n.index === focus || n.id === selectedRef.current;
      const lit = isFocus || (around?.has(n.index) ?? false) || (q !== "" && n.id.toLowerCase().includes(q));
      const always = v.k > 2.4 || (hubsRef.current.has(n.index) && v.k > 0.45);
      if (!lit && !always) continue;
      wanted.push({ n, rank: (isFocus ? 2_000_000 : 0) + (lit ? 1_000_000 : 0) + n.degree });
    }
    wanted.sort((a, b) => b.rank - a.rank);
    const placed: Array<[number, number, number, number]> = [];
    const lineH = 12 / v.k;
    for (const { n, rank } of wanted) {
      const text = base(n.id);
      const width = ctx.measureText(text).width;
      const x0 = n.x - width / 2;
      const y0 = n.y + n.r + 2 / v.k;
      const clash = placed.some(([ax, ay, bx, by]) => x0 < bx && x0 + width > ax && y0 < by && y0 + lineH > ay);
      if (clash && rank < 2_000_000) continue;
      placed.push([x0, y0, x0 + width, y0 + lineH]);
      ctx.globalAlpha = faded(n) ? 0.25 : 1;
      ctx.fillStyle = "#ececf5";
      ctx.fillText(text, n.x, n.y + n.r + 12 / v.k);
    }
    ctx.globalAlpha = 1;
  }, [langOf]);

  const frame = useCallback(() => {
    rafRef.current = 0;
    const sim = simRef.current;
    if (sim && !pausedRef.current && !sim.settled) sim.tick();
    draw();
    if (sim && ((!pausedRef.current && !sim.settled) || dragRef.current !== null)) rafRef.current = requestAnimationFrame(frame);
  }, [draw]);
  const kick = useCallback(() => {
    if (rafRef.current === 0) rafRef.current = requestAnimationFrame(frame);
  }, [frame]);

  const refit = useCallback(() => {
    const sim = simRef.current;
    if (!sim) return;
    viewRef.current = fitView(sim.nodes, sizeRef.current.w, sizeRef.current.h, 48, visibleNode);
    kick();
  }, [kick, visibleNode]);

  /* a new project / a new scan → a new layout, computed up front so the map does not "boil" */
  useEffect(() => {
    const sim = new ForceSim(
      nodes.map((n) => ({ id: n.id, degree: n.degree })),
      edges,
    );
    sim.settle(300);
    simRef.current = sim;
    colorsRef.current = nodes.map((n) => languageColor(n.language));
    // name only the best-connected files by default; the rest appear on hover, search or zoom
    hubsRef.current = new Set(
      sim.nodes
        .filter((n) => n.degree > 0)
        .sort((a, b) => b.degree - a.degree)
        .slice(0, Math.max(6, Math.min(16, Math.round(nodes.length / 6))))
        .map((n) => n.index),
    );
    hoverRef.current = -1;
    setTip(null);
    refit();
  }, [nodes, edges, refit]);

  /* size of the canvas follows its container */
  useEffect(() => {
    const wrap = wrapRef.current;
    const canvas = canvasRef.current;
    if (!wrap || !canvas) return;
    const apply = () => {
      const w = wrap.clientWidth || 800;
      const h = wrap.clientHeight || 520;
      const dpr = window.devicePixelRatio || 1;
      sizeRef.current = { w, h };
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      canvas.style.width = `${String(w)}px`;
      canvas.style.height = `${String(h)}px`;
      refit();
    };
    apply();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(apply);
    observer.observe(wrap);
    return () => observer.disconnect();
  }, [refit]);

  /* selection / search / language filter only need a repaint */
  useEffect(() => {
    selectedRef.current = selected;
    queryRef.current = query;
    hiddenRef.current = hidden;
    kick();
  }, [selected, query, hidden, kick]);

  useEffect(() => {
    pausedRef.current = paused;
    if (!paused) kick();
  }, [paused, kick]);

  useEffect(
    () => () => {
      if (rafRef.current !== 0) cancelAnimationFrame(rafRef.current);
    },
    [],
  );

  const zoomAt = useCallback(
    (sx: number, sy: number, factor: number) => {
      const v = viewRef.current;
      const k = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, v.k * factor));
      viewRef.current = { k, x: sx - ((sx - v.x) * k) / v.k, y: sy - ((sy - v.y) * k) / v.k };
      kick();
    },
    [kick],
  );

  /* wheel needs a non-passive listener to keep the page from scrolling */
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = canvas.getBoundingClientRect();
      zoomAt(e.clientX - rect.left, e.clientY - rect.top, Math.exp(-e.deltaY * 0.0015));
    };
    canvas.addEventListener("wheel", onWheel, { passive: false });
    return () => canvas.removeEventListener("wheel", onWheel);
  }, [zoomAt]);

  const local = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    return { sx: e.clientX - rect.left, sy: e.clientY - rect.top };
  };

  const onPointerDown = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const sim = simRef.current;
    if (!sim) return;
    const { sx, sy } = local(e);
    e.currentTarget.setPointerCapture?.(e.pointerId);
    const index = pickNode(sim.nodes, viewRef.current, sx, sy, visibleNode);
    if (index >= 0) {
      const n = sim.nodes[index];
      if (n) n.pinned = true;
      dragRef.current = { kind: "node", index, startX: sx, startY: sy, moved: false };
      sim.reheat(0.3);
    } else {
      dragRef.current = { kind: "pan", lastX: sx, lastY: sy, startX: sx, startY: sy, moved: false };
    }
    setTip(null);
    kick();
  };

  const onPointerMove = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const sim = simRef.current;
    if (!sim) return;
    const { sx, sy } = local(e);
    const drag = dragRef.current;
    if (drag !== null) {
      if (Math.hypot(sx - drag.startX, sy - drag.startY) > 3) drag.moved = true;
      if (drag.kind === "node") {
        const n = sim.nodes[drag.index];
        if (n && drag.moved) {
          const p = screenToWorld(viewRef.current, sx, sy);
          n.x = p.x;
          n.y = p.y;
          sim.reheat(0.3);
        }
      } else {
        const v = viewRef.current;
        viewRef.current = { ...v, x: v.x + sx - drag.lastX, y: v.y + sy - drag.lastY };
        drag.lastX = sx;
        drag.lastY = sy;
      }
      kick();
      return;
    }
    const index = pickNode(sim.nodes, viewRef.current, sx, sy, visibleNode);
    if (index !== hoverRef.current) {
      hoverRef.current = index;
      const meta = index >= 0 ? nodesRef.current[index] : undefined;
      setTip(meta ? { x: sx, y: sy, node: meta } : null);
      kick();
    }
  };

  const endDrag = (e: React.PointerEvent<HTMLCanvasElement>, cancelled: boolean) => {
    const sim = simRef.current;
    const drag = dragRef.current;
    dragRef.current = null;
    e.currentTarget.releasePointerCapture?.(e.pointerId);
    if (sim && drag?.kind === "node") {
      const n = sim.nodes[drag.index];
      if (n) n.pinned = false;
      if (!drag.moved && !cancelled && n) onSelect(n.id);
    }
    kick();
  };

  const onPointerLeave = () => {
    if (hoverRef.current !== -1) {
      hoverRef.current = -1;
      setTip(null);
      kick();
    }
  };

  const legend = useMemo(() => {
    const counts = new Map<string, number>();
    for (const n of nodes) counts.set(n.language ?? "—", (counts.get(n.language ?? "—") ?? 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [nodes]);

  const toggleLanguage = (lang: string) =>
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(lang)) next.delete(lang);
      else next.add(lang);
      return next;
    });

  const btn =
    "cursor-pointer rounded-md border border-[#2a2a38] bg-[#15151e] px-2.5 py-1 text-xs text-[#d9d9e6] hover:bg-[#1e1e2b] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#ffffff]";
  const centerZoom = (factor: number) => zoomAt(sizeRef.current.w / 2, sizeRef.current.h / 2, factor);

  return (
    <div className="overflow-hidden rounded-lg border border-[#2a2a38] bg-[#0b0b10] text-[#d9d9e6]">
      <div className="flex flex-wrap items-center gap-2 border-b border-[#1c1c28] px-3 py-2">
        <button type="button" className={btn} onClick={() => centerZoom(1.3)} aria-label={t("memory.graphmap.zoomIn")}>
          +
        </button>
        <button type="button" className={btn} onClick={() => centerZoom(1 / 1.3)} aria-label={t("memory.graphmap.zoomOut")}>
          −
        </button>
        <button type="button" className={btn} onClick={refit}>
          {t("memory.graphmap.fit")}
        </button>
        <button type="button" className={btn} aria-pressed={paused} onClick={() => setPaused((p) => !p)}>
          {paused ? t("memory.graphmap.resume") : t("memory.graphmap.freeze")}
        </button>
        <span className="ml-auto text-xs text-[#8b8b9c]">{t("memory.graphmap.help")}</span>
      </div>

      <div ref={wrapRef} className="relative h-[58vh] min-h-[340px] w-full">
        <canvas
          ref={canvasRef}
          role="img"
          aria-label={t("memory.graphmap.label")}
          className="absolute inset-0 touch-none cursor-grab active:cursor-grabbing"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={(e) => endDrag(e, false)}
          onPointerCancel={(e) => endDrag(e, true)}
          onPointerLeave={onPointerLeave}
        />
        {tip !== null && (
          <div
            role="tooltip"
            className="pointer-events-none absolute z-10 max-w-[280px] rounded-md border border-[#2a2a38] bg-[#15151e] px-2.5 py-1.5 text-xs shadow-lg"
            style={{ left: Math.min(tip.x + 14, Math.max(0, sizeRef.current.w - 290)), top: Math.min(tip.y + 14, Math.max(0, sizeRef.current.h - 90)) }}
          >
            <p className="break-all font-mono text-[#ffffff]">{tip.node.id}</p>
            <p className="mt-0.5 text-[#8b8b9c]">
              {tip.node.language ?? "—"} · {t("memory.graphmap.links", { n: tip.node.degree })}
            </p>
            {tip.node.summary !== "" && <p className="mt-1 line-clamp-3 text-[#c4c4d4]">{tip.node.summary}</p>}
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-1.5 border-t border-[#1c1c28] px-3 py-2" role="group" aria-label={t("memory.graphmap.legend")}>
        {legend.map(([lang, count]) => {
          const off = hidden.has(lang);
          return (
            <button
              key={lang}
              type="button"
              aria-pressed={!off}
              onClick={() => toggleLanguage(lang)}
              className={`${btn} inline-flex items-center gap-1.5 ${off ? "opacity-40" : ""}`}
            >
              <span aria-hidden className="inline-block h-2 w-2 rounded-full" style={{ background: languageColor(lang === "—" ? null : lang) }} />
              {lang} <span className="text-[#8b8b9c]">{count}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
