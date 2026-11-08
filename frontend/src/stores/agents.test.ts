import { beforeEach, describe, expect, it, vi } from "vitest";

const mock = vi.hoisted(() => ({
  listAgents: vi.fn(),
  updateAgent: vi.fn(),
  createAgent: vi.fn(),
  deleteAgent: vi.fn(),
  listProjects: vi.fn(),
}));

vi.mock("../services/engine", () => ({ engine: mock, toHumanMessage: () => "échec" }));

import { useAgentsStore } from "./agents";
import { useProjectsStore } from "./projects";
import { useUiStore } from "./ui";
import type { Agent } from "../types/engine";

const backend = { name: "backend", role: "backend", builtin: true, enabled: true } as Agent;
const custom = { name: "relecteur", role: "Relecteur", builtin: false, enabled: true } as Agent;

describe("agents store", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mock.updateAgent.mockResolvedValue(undefined);
    mock.deleteAgent.mockResolvedValue(undefined);
    useProjectsStore.setState({ projects: [{ id: "P1", name: "x", status: "active" }] as never, status: "ready" });
    useUiStore.setState({ lastProjectId: "P1" });
    useAgentsStore.setState({ agents: [backend, custom], actionError: null });
  });

  it("scopes every change to a project, as the engine requires", async () => {
    await useAgentsStore.getState().setEnabled(backend, false);
    expect(mock.updateAgent).toHaveBeenCalledWith("P1", "backend", { enabled: false });
  });

  it("addresses a custom agent by its unique name", async () => {
    await useAgentsStore.getState().remove(custom);
    expect(mock.deleteAgent).toHaveBeenCalledWith("P1", "relecteur");
  });

  it("explains instead of failing when no project exists", async () => {
    useProjectsStore.setState({ projects: [] });
    useUiStore.setState({ lastProjectId: null });
    await useAgentsStore.getState().setEnabled(backend, false);
    expect(mock.updateAgent).not.toHaveBeenCalled();
    expect(useAgentsStore.getState().actionError).not.toBeNull();
  });

  it("restores the toggle when the engine refuses", async () => {
    mock.updateAgent.mockRejectedValue(new Error("x"));
    await useAgentsStore.getState().setEnabled(backend, false);
    expect(useAgentsStore.getState().agents[0]?.enabled).toBe(true);
    expect(useAgentsStore.getState().actionError).toBe("échec");
  });
});
