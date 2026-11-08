import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { streamConversation, type StreamHandlers } from "./engine";

vi.mock("./endpoint", () => ({
  getEngineEndpoint: () => Promise.resolve({ baseUrl: "http://e", token: "t" }),
  isTauri: () => false,
  pickDirectory: () => Promise.resolve(null),
}));

function sse(...blocks: string[]): Response {
  return new Response(blocks.join(""), { status: 200 });
}
const event = (id: number, type: string, data: object): string =>
  `id: ${String(id)}\nevent: ${type}\ndata: ${JSON.stringify(data)}\n\n`;
const REPLAY_END = "event: replay_end\ndata: {}\n\n";

function handlers(): Required<StreamHandlers> {
  return {
    onToken: vi.fn(),
    onAgentStatus: vi.fn(),
    onDecision: vi.fn(),
    onActionRequest: vi.fn(),
    onDone: vi.fn(),
    onError: vi.fn(),
    onReplayEnd: vi.fn(),
  };
}

describe("streamConversation", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("does not act on what happened before the conversation was opened", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          sse(
            event(1, "token", { text: "ancien" }),
            event(2, "error", { message: "OLD FAILURE" }),
            event(3, "done", {}),
            event(4, "decision", { kind: "plan_tasks", count: 2 }),
            REPLAY_END,
            event(5, "token", { text: "neuf" }),
          ),
        ),
      ),
    );
    const h = handlers();
    const stop = streamConversation("c", h);
    await vi.waitFor(() => {
      expect(h.onToken).toHaveBeenCalledWith("neuf");
    });
    stop();
    expect(h.onToken).toHaveBeenCalledTimes(1);
    expect(h.onError).not.toHaveBeenCalled();
    expect(h.onDone).not.toHaveBeenCalled();
    expect(h.onDecision).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "plan_tasks", historical: true }),
    );
    expect(h.onReplayEnd).toHaveBeenCalledTimes(1);
  });

  it("flags a single failed task so the input stays locked", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(sse(REPLAY_END, event(1, "error", { message: "x", task_id: "T" }))),
      ),
    );
    const h = handlers();
    const stop = streamConversation("c", h);
    await vi.waitFor(() => {
      expect(h.onError).toHaveBeenCalledWith("x", { midRun: true });
    });
    stop();
  });

  it("keeps trying after a network failure, and says so only once", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new Error("down"))
      .mockRejectedValueOnce(new Error("down"))
      .mockImplementation(() => Promise.resolve(sse(REPLAY_END, event(9, "done", {}))));
    vi.stubGlobal("fetch", fetchMock);
    const h = handlers();
    const stop = streamConversation("c", h);
    await vi.advanceTimersByTimeAsync(6000);
    await vi.waitFor(() => {
      expect(h.onDone).toHaveBeenCalled();
    });
    stop();
    expect(h.onError).toHaveBeenCalledTimes(1);
  });

  it("does not hammer the engine when an idle stream closes", async () => {
    const fetchMock = vi.fn(() => Promise.resolve(sse(REPLAY_END)));
    vi.stubGlobal("fetch", fetchMock);
    const stop = streamConversation("c", handlers());
    await vi.advanceTimersByTimeAsync(1000);
    stop();
    expect(fetchMock.mock.calls.length).toBeLessThanOrEqual(3);
  });
});
