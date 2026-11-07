import { describe, expect, it } from "vitest";
import { ForceSim, fitView, languageColor, pickNode, radiusFor, screenToWorld } from "./forceLayout";

/** Two tight clusters (a hub + 6 files each) joined by one edge, and one lonely file. */
function sample() {
  const nodes: Array<{ id: string; degree: number }> = [];
  const edges: Array<{ source: string; target: string }> = [];
  for (const g of ["a", "b"]) {
    nodes.push({ id: `${g}/hub.ts`, degree: 6 });
    for (let i = 0; i < 6; i++) {
      nodes.push({ id: `${g}/f${String(i)}.ts`, degree: 1 });
      edges.push({ source: `${g}/f${String(i)}.ts`, target: `${g}/hub.ts` });
    }
  }
  edges.push({ source: "a/hub.ts", target: "b/hub.ts" });
  nodes.push({ id: "lonely.md", degree: 0 });
  return { nodes, edges };
}
const dist = (a: { x: number; y: number }, b: { x: number; y: number }) => Math.hypot(a.x - b.x, a.y - b.y);

describe("ForceSim", () => {
  it("is deterministic: same data, same layout", () => {
    const { nodes, edges } = sample();
    const one = new ForceSim(nodes, edges);
    const two = new ForceSim(nodes, edges);
    one.settle();
    two.settle();
    expect(one.nodes.map((n) => [n.x, n.y])).toEqual(two.nodes.map((n) => [n.x, n.y]));
  });

  it("keeps linked files close, unrelated files apart, and never produces NaN", () => {
    const { nodes, edges } = sample();
    const sim = new ForceSim(nodes, edges);
    sim.settle();
    for (const n of sim.nodes) expect(Number.isFinite(n.x) && Number.isFinite(n.y)).toBe(true);
    const byId = new Map(sim.nodes.map((n) => [n.id, n]));
    const hubA = byId.get("a/hub.ts")!;
    const leafA = byId.get("a/f0.ts")!;
    const leafB = byId.get("b/f0.ts")!;
    expect(dist(hubA, leafA)).toBeLessThan(dist(hubA, leafB)); // a file sits near its own hub
    // no two nodes sit on top of each other
    let min = Infinity;
    for (const x of sim.nodes) for (const y of sim.nodes) if (x !== y) min = Math.min(min, dist(x, y));
    expect(min).toBeGreaterThan(8);
    // and the whole map stays in a reasonable area
    const extent = Math.max(...sim.nodes.map((n) => Math.hypot(n.x, n.y)));
    expect(extent).toBeLessThan(600);
  });

  it("settles by itself and wakes up again when asked", () => {
    const { nodes, edges } = sample();
    const sim = new ForceSim(nodes, edges);
    sim.settle(2000);
    expect(sim.settled).toBe(true);
    sim.reheat(0.4);
    expect(sim.settled).toBe(false);
  });

  it("holds a pinned node in place while the others move", () => {
    const { nodes, edges } = sample();
    const sim = new ForceSim(nodes, edges);
    const first = sim.nodes[0]!;
    first.pinned = true;
    const [x, y] = [first.x, first.y];
    sim.settle();
    expect([first.x, first.y]).toEqual([x, y]);
  });

  it("ignores edges to unknown files, self-links and duplicates", () => {
    const sim = new ForceSim(
      [
        { id: "a", degree: 1 },
        { id: "b", degree: 1 },
      ],
      [
        { source: "a", target: "b" },
        { source: "b", target: "a" },
        { source: "a", target: "a" },
        { source: "a", target: "ghost" },
      ],
    );
    expect(sim.links).toHaveLength(1);
    expect([...(sim.neighbors[0] ?? [])]).toEqual([1]);
  });

  it("copes with an empty project", () => {
    const sim = new ForceSim([], []);
    expect(() => sim.settle()).not.toThrow();
    expect(fitView(sim.nodes, 800, 600)).toEqual({ x: 400, y: 300, k: 1 });
  });
});

describe("view helpers", () => {
  it("picks the node under the pointer, accounting for pan and zoom", () => {
    const sim = new ForceSim([{ id: "a", degree: 4 }], []);
    const n = sim.nodes[0]!;
    n.x = 10;
    n.y = 20;
    const view = { x: 100, y: 50, k: 2 }; // the node is drawn at (120, 90)
    expect(pickNode(sim.nodes, view, 120, 90)).toBe(0);
    expect(pickNode(sim.nodes, view, 300, 300)).toBe(-1);
    expect(pickNode(sim.nodes, view, 120, 90, () => false)).toBe(-1); // hidden nodes cannot be picked
    expect(screenToWorld(view, 120, 90)).toEqual({ x: 10, y: 20 });
  });

  it("fits every node in the viewport", () => {
    const { nodes, edges } = sample();
    const sim = new ForceSim(nodes, edges);
    sim.settle();
    const view = fitView(sim.nodes, 800, 500);
    for (const n of sim.nodes) {
      const sx = n.x * view.k + view.x;
      const sy = n.y * view.k + view.y;
      expect(sx).toBeGreaterThanOrEqual(0);
      expect(sx).toBeLessThanOrEqual(800);
      expect(sy).toBeGreaterThanOrEqual(0);
      expect(sy).toBeLessThanOrEqual(500);
    }
  });

  it("gives hubs a bigger dot and every language a stable colour", () => {
    expect(radiusFor(9)).toBeGreaterThan(radiusFor(1));
    expect(radiusFor(10_000)).toBeLessThanOrEqual(14);
    expect(languageColor("TypeScript")).toBe(languageColor("TypeScript"));
    expect(languageColor("Brainfuck")).toBe(languageColor("Brainfuck"));
    expect(languageColor("Brainfuck")).not.toBe(languageColor("Zig"));
    expect(languageColor(null)).toMatch(/^#/);
  });
});
