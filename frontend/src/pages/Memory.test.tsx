import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { MemoryFileDetail, MemoryItem, MemoryOverview } from "../types/engine";

const engineMock = vi.hoisted(() => ({
  listProjects: vi.fn(),
  memoryOverview: vi.fn(),
  listMemory: vi.fn(),
  createMemory: vi.fn(),
  promoteMemory: vi.fn(),
  updateMemory: vi.fn(),
  deleteMemory: vi.fn(),
  memoryFiles: vi.fn(),
  memoryFile: vi.fn(),
  memoryContext: vi.fn(),
  scanMemory: vi.fn(),
}));
vi.mock("../services/engine", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../services/engine")>();
  return { ...actual, engine: engineMock };
});
vi.mock("../services/endpoint", () => ({ pickDirectory: vi.fn() }));

import { Memory } from "./Memory";
import { useProjectsStore } from "../stores/projects";

const overview: MemoryOverview = {
  project_id: "p1",
  folder: "C:\\work\\site",
  items: { short: 1, long: 1 },
  files: { count: 3, bytes: 4000, languages: { TypeScript: 3 }, last_scan_at: "2026-11-07T10:00:00", last_scan: null },
  context: { tokens: 120, reread_tokens_avoided: 880 },
};
const item = (over: Partial<MemoryItem>): MemoryItem => ({
  id: "m1", project_id: "p1", tier: "long", kind: "decision", title: "Use Vite", content: "fast HMR",
  source: "user", pinned: false, expires_at: null, created_at: "2026-11-07T09:00:00", updated_at: "2026-11-07T09:00:00", ...over,
});
const detail: MemoryFileDetail = {
  path: "src/main.ts", language: "TypeScript", size: 321, summary: "App entry point.", symbols: ["boot"], external: ["react"],
  imports: [{ path: "src/lib/greet.ts", summary: "Says hello.", language: "TypeScript" }],
  imported_by: [{ path: "src/index.html", summary: "", language: null }], scanned_at: "2026-11-07T10:00:00",
};

beforeEach(() => {
  Object.values(engineMock).forEach((fn) => fn.mockReset());
  useProjectsStore.setState({ projects: [], status: "idle", error: null });
  engineMock.listProjects.mockResolvedValue([{ id: "p1", name: "Demo", status: "active" }]);
  engineMock.memoryOverview.mockResolvedValue(overview);
  engineMock.listMemory.mockResolvedValue({
    items: [item({}), item({ id: "m2", tier: "short", kind: "task_result", title: "Design done", source: "system", expires_at: "2026-11-21T09:00:00" })],
  });
  engineMock.memoryFiles.mockResolvedValue({
    files: [
      { path: "src/main.ts", language: "TypeScript", size: 321, summary: "App entry point.", imports: 1, imported_by: 1 },
      { path: "src/lib/greet.ts", language: "TypeScript", size: 90, summary: "Says hello.", imports: 0, imported_by: 1 },
    ],
  });
  engineMock.memoryFile.mockResolvedValue(detail);
});
afterEach(cleanup);

describe("Memory page", () => {
  it("shows the two tiers, marks automatic captures and the forgetting date", async () => {
    render(<Memory />);
    expect(await screen.findByText("Use Vite")).toBeTruthy();
    expect(screen.getByText("Design done")).toBeTruthy();
    expect(screen.getByText(/capturé automatiquement/)).toBeTruthy();
    expect(screen.getByText(/Sera oublié le/)).toBeTruthy();
    expect(screen.getByText("Long terme", { selector: "dt" })).toBeTruthy();
    expect(screen.getByText("≈ 880 tok")).toBeTruthy(); // the saving is shown as an estimate
  });

  it("promotes a short-term memory to long-term", async () => {
    engineMock.promoteMemory.mockResolvedValue(item({ id: "m2", tier: "long" }));
    render(<Memory />);
    fireEvent.click(await screen.findByRole("button", { name: "Garder à long terme" }));
    await waitFor(() => expect(engineMock.promoteMemory).toHaveBeenCalledWith("p1", "m2"));
  });

  it("creates a memory", async () => {
    engineMock.createMemory.mockResolvedValue(item({ title: "No cloud" }));
    render(<Memory />);
    fireEvent.click(await screen.findByRole("button", { name: "Ajouter un souvenir" }));
    fireEvent.change(await screen.findByLabelText("Titre"), { target: { value: "No cloud" } });
    fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
    await waitFor(() =>
      expect(engineMock.createMemory).toHaveBeenCalledWith("p1", expect.objectContaining({ title: "No cloud", tier: "long" })),
    );
  });

  it("navigates the file graph in both directions and reports files that were not re-read", async () => {
    engineMock.scanMemory.mockResolvedValue({ files: 2, read: 0, unchanged: 2, removed: 0, skipped: 0, truncated: false, bytes_covered: 411 });
    render(<Memory />);
    fireEvent.click(await screen.findByRole("radio", { name: "Fichiers" }));
    fireEvent.click(await screen.findByRole("button", { name: /main\.ts/ }));
    expect(await screen.findByText("App entry point.", { selector: "p" })).toBeTruthy();
    expect(screen.getByText(/react/)).toBeTruthy();
    // linked files are clickable to move through the graph
    fireEvent.click(screen.getAllByRole("button", { name: /src\/lib\/greet\.ts/ })[0]!);
    await waitFor(() => expect(engineMock.memoryFile).toHaveBeenLastCalledWith("p1", "src/lib/greet.ts"));

    fireEvent.click(screen.getByRole("button", { name: "Analyser le dossier" }));
    expect(await screen.findByText(/0 relus, 2 inchangés/)).toBeTruthy();
  });

  it("shows exactly what the agents receive", async () => {
    engineMock.memoryContext.mockResolvedValue({
      text: "## Project memory\n- [decision] Use Vite", tokens: 12, budget_tokens: 1500, items: 1, files: 3,
    });
    render(<Memory />);
    fireEvent.click(await screen.findByRole("radio", { name: "Ce que voient les agents" }));
    expect(await screen.findByText(/Use Vite/, { selector: "pre" })).toBeTruthy();
    expect(screen.getByText(/12 tokens sur 1500/)).toBeTruthy();
  });
});
