import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const engineMock = vi.hoisted(() => ({ importProviderToken: vi.fn() }));
vi.mock("../../services/engine", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../services/engine")>();
  return { ...actual, engine: engineMock };
});

import { ExecutionSelector } from "../chat/ExecutionSelector";
import { Modal } from "./Modal";
import { TokenImport } from "./TokenImport";

beforeEach(() => engineMock.importProviderToken.mockReset());
afterEach(cleanup);

describe("Expert · Complet", () => {
  it("can be selected, and each expert entry says which sub-mode it runs", () => {
    const onChange = vi.fn();
    render(<ExecutionSelector value="simple" onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: /Mode d'exécution/ }));
    const complete = screen.getByRole("radio", { name: /Expert · Complet/ }) as HTMLButtonElement;
    expect(complete.disabled).toBe(false);
    fireEvent.click(complete);
    expect(onChange).toHaveBeenLastCalledWith("expert", "complet");
    fireEvent.click(screen.getByRole("button", { name: /Mode d'exécution/ }));
    fireEvent.click(screen.getByRole("radio", { name: /Expert · Analyse/ }));
    expect(onChange).toHaveBeenLastCalledWith("expert", "analyse");
  });

  it("shows Complet as the current choice", () => {
    render(<ExecutionSelector value="expert" submode="complet" onChange={() => undefined} />);
    expect(screen.getByRole("button", { name: /Mode d'exécution/ }).textContent).toContain("Complet");
  });
});

describe("Modal", () => {
  it("is rendered in <body>, so an animated ancestor cannot trap it inside a card", () => {
    const { container } = render(
      <div style={{ transform: "translateY(0)" }}>
        <Modal open title="Retirer ce serveur ?" onClose={() => undefined}>
          <p>contenu</p>
        </Modal>
      </div>,
    );
    const dialog = screen.getByRole("dialog");
    expect(container.contains(dialog)).toBe(false);
    expect(document.body.contains(dialog)).toBe(true);
    expect(dialog.parentElement?.className).toContain("fixed");
  });
});

describe("TokenImport", () => {
  it("masks a Claude token, sends it, and forgets it once accepted", async () => {
    engineMock.importProviderToken.mockResolvedValue({ state: "signed_in", reachable: true });
    const onDone = vi.fn();
    render(<TokenImport id="claude-code" onDone={onDone} />);
    const input = screen.getByLabelText("Jeton Claude Code") as HTMLInputElement;
    expect(input.type).toBe("password");
    fireEvent.change(input, { target: { value: "  sk-ant-oat01-abc  " } });
    fireEvent.click(screen.getByRole("button", { name: "Vérifier et importer" }));
    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(engineMock.importProviderToken).toHaveBeenCalledWith("claude-code", "sk-ant-oat01-abc");
    expect(input.value).toBe(""); // the token does not stay in the interface
  });

  it("shows the reason when the token is refused and keeps the form", async () => {
    engineMock.importProviderToken.mockResolvedValue({
      state: "failed",
      reachable: false,
      detail: "The token was rejected: Invalid bearer token",
    });
    const onDone = vi.fn();
    render(<TokenImport id="claude-code" onDone={onDone} />);
    fireEvent.change(screen.getByLabelText("Jeton Claude Code"), { target: { value: "sk-ant-x" } });
    fireEvent.click(screen.getByRole("button", { name: "Vérifier et importer" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain("Invalid bearer token");
    expect(onDone).not.toHaveBeenCalled();
  });

  it("asks for the whole auth.json for Codex", () => {
    render(<TokenImport id="codex" onDone={() => undefined} />);
    const field = screen.getByLabelText("Jeton Codex");
    expect(field.tagName).toBe("TEXTAREA");
    expect((screen.getByRole("button", { name: "Vérifier et importer" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
