import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { PreviewInfo } from "../../types/engine";

const engineMock = vi.hoisted(() => ({
  getPreview: vi.fn(),
  configurePreview: vi.fn(),
  startPreview: vi.fn(),
  stopPreview: vi.fn(),
  restartPreview: vi.fn(),
  openPreviewExternal: vi.fn(),
}));
const pickMock = vi.hoisted(() => vi.fn());

vi.mock("../../services/engine", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../services/engine")>();
  return { ...actual, engine: engineMock };
});
vi.mock("../../services/endpoint", () => ({ pickDirectory: pickMock }));

import { PreviewPanel } from "./PreviewPanel";

const base: PreviewInfo = {
  project_id: "p1",
  configured: true,
  state: "stopped",
  root_path: "C:\\work\\site",
  app_root: "C:\\work\\site",
  framework: "vite",
  label: "React (Vite)",
  package_manager: "npm",
  script: "dev",
  deps_installed: true,
  hot_update: "hmr",
  runnable: true,
  needs_trust: true,
  trusted: false,
  logs: [],
};

function serve(info: PreviewInfo) {
  engineMock.getPreview.mockResolvedValue(info);
}

beforeEach(() => {
  Object.values(engineMock).forEach((fn) => fn.mockReset());
  pickMock.mockReset();
});
afterEach(cleanup);

describe("PreviewPanel", () => {
  it("asks for a folder when the project has none, and configures the picked one", async () => {
    serve({ project_id: "p1", configured: false, state: "stopped" });
    pickMock.mockResolvedValue("C:\\work\\site");
    engineMock.configurePreview.mockResolvedValue(base);
    render(<PreviewPanel projectId="p1" />);
    expect(await screen.findByText("Choisissez le dossier du projet web")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Choisir un dossier…" }));
    await waitFor(() =>
      expect(engineMock.configurePreview).toHaveBeenCalledWith("p1", { root_path: "C:\\work\\site" }),
    );
  });

  it("shows the iframe only when the server really answers, isolated and on a white background", async () => {
    serve({ ...base, state: "ready", port: 5173, url: "http://127.0.0.1:5173/", trusted: true, needs_trust: false });
    render(<PreviewPanel projectId="p1" />);
    const frame = (await screen.findByTitle("Aperçu")) as HTMLIFrameElement;
    expect(frame.getAttribute("src")).toBe("http://127.0.0.1:5173/");
    const sandbox = frame.getAttribute("sandbox") ?? "";
    expect(sandbox).toContain("allow-scripts");
    expect(sandbox).not.toContain("allow-top-navigation"); // cannot navigate the app away
    expect(sandbox).not.toContain("allow-downloads");
    expect(frame.getAttribute("referrerpolicy")).toBe("no-referrer");
    expect(frame.className).toContain("bg-white"); // no black page from the dark theme
    expect(screen.getByText("Prêt")).toBeTruthy();
    expect(screen.getByText("port 5173")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Actualiser" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Ouvrir dans le navigateur" })).toBeTruthy();
  });

  it("never shows a page (or a URL) while the server is still starting", async () => {
    serve({ ...base, state: "starting", port: 5173, url: null, trusted: true, needs_trust: false });
    render(<PreviewPanel projectId="p1" />);
    expect(await screen.findByText("Démarrage…")).toBeTruthy();
    expect(screen.queryByTitle("Aperçu")).toBeNull();
    expect(screen.queryByText(/127\.0\.0\.1/)).toBeNull();
  });

  it("keeps the page visible but explains a compile error", async () => {
    serve({
      ...base,
      state: "compile_error",
      url: "http://127.0.0.1:5173/",
      port: 5173,
      error: "Error: Failed to compile ./src/App.tsx",
      trusted: true,
      needs_trust: false,
    });
    render(<PreviewPanel projectId="p1" />);
    expect(await screen.findByText(/Failed to compile/)).toBeTruthy();
    expect(screen.getAllByText("Erreur de compilation").length).toBeGreaterThan(0);
    expect(screen.getByTitle("Aperçu")).toBeTruthy();
  });

  it("explains a failure instead of a blank page and offers a restart", async () => {
    serve({ ...base, state: "failed", error: "The server stopped unexpectedly (code 3).", trusted: true, needs_trust: false });
    engineMock.restartPreview.mockResolvedValue({ ...base, state: "starting" });
    render(<PreviewPanel projectId="p1" />);
    expect(await screen.findByText(/stopped unexpectedly/)).toBeTruthy();
    expect(screen.queryByTitle("Aperçu")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Redémarrer" }));
    await waitFor(() => expect(engineMock.restartPreview).toHaveBeenCalledWith("p1"));
  });

  it("requires the user to trust the folder before running its scripts", async () => {
    serve(base);
    engineMock.startPreview.mockResolvedValue({ ...base, state: "starting", trusted: true });
    render(<PreviewPanel projectId="p1" />);
    const start = (await screen.findByRole("button", { name: "Démarrer l'aperçu" })) as HTMLButtonElement;
    expect(start.disabled).toBe(true);
    fireEvent.click(screen.getByRole("checkbox"));
    expect(start.disabled).toBe(false);
    fireEvent.click(start);
    await waitFor(() =>
      expect(engineMock.startPreview).toHaveBeenCalledWith("p1", { trust: true, install_deps: false }),
    );
  });

  it("offers to install missing dependencies", async () => {
    serve({ ...base, state: "deps_missing", deps_installed: false });
    engineMock.startPreview.mockResolvedValue({ ...base, state: "installing" });
    render(<PreviewPanel projectId="p1" />);
    fireEvent.click(await screen.findByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Installer les dépendances et démarrer" }));
    await waitFor(() =>
      expect(engineMock.startPreview).toHaveBeenCalledWith("p1", { trust: true, install_deps: true }),
    );
  });

  it("starts a trusted project by itself", async () => {
    serve({ ...base, trusted: true, needs_trust: false });
    engineMock.startPreview.mockResolvedValue({ ...base, state: "starting" });
    render(<PreviewPanel projectId="p1" />);
    await waitFor(() => expect(engineMock.startPreview).toHaveBeenCalledWith("p1", {}));
  });

  it("lets the user pick the app when several are found, or the framework when unknown", async () => {
    const ambiguous: PreviewInfo = {
      ...base,
      framework: null,
      runnable: false,
      detection_error: "Several web apps found: pick one (sub-folder).",
      candidates: ["admin", "web"],
    };
    serve(ambiguous);
    engineMock.configurePreview.mockResolvedValue(ambiguous); // still unresolved after each pick
    render(<PreviewPanel projectId="p1" />);
    fireEvent.click(await screen.findByRole("button", { name: "web" }));
    await waitFor(() =>
      expect(engineMock.configurePreview).toHaveBeenCalledWith("p1", { subdir: "web", root_path: "C:\\work\\site" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "next" }));
    await waitFor(() =>
      expect(engineMock.configurePreview).toHaveBeenLastCalledWith("p1", {
        framework: "next",
        subdir: undefined,
        root_path: "C:\\work\\site",
      }),
    );
  });
});
