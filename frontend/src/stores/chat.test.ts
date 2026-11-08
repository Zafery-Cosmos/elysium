import { beforeEach, describe, expect, it, vi } from "vitest";

type Handlers = {
  onDone?: () => void;
  onDecision?: (e: object) => void;
  onReplayEnd?: () => void;
};
const streams: Array<{ id: string; handlers: Handlers }> = [];

const mock = vi.hoisted(() => ({
  listConversations: vi.fn(),
  listMessages: vi.fn(),
  createConversation: vi.fn(),
  sendMessage: vi.fn(),
  listTasks: vi.fn(),
  rejectPlan: vi.fn(),
}));

vi.mock("../services/engine", () => ({
  engine: mock,
  toHumanMessage: () => "échec",
  streamConversation: (id: string, handlers: Handlers) => {
    streams.push({ id, handlers });
    return () => undefined;
  },
}));

import { useChatStore } from "./chat";

const deferred = <T>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
};
const flush = () => new Promise((r) => setTimeout(r, 0));

describe("chat store", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    streams.length = 0;
    useChatStore.getState().close();
    useChatStore.setState({ projectId: null, conversationId: null, messages: [], sending: false, pendingPlan: null, failedDraft: null });
    mock.sendMessage.mockResolvedValue({});
    mock.listTasks.mockResolvedValue([]);
  });

  it("does not move a first message's conversation into the project opened meanwhile", async () => {
    mock.listConversations.mockResolvedValue([]);
    await useChatStore.getState().openForProject("A");
    const created = deferred<{ id: string }>();
    mock.createConversation.mockReturnValue(created.promise);
    const sending = useChatStore.getState().send("pour A");
    await useChatStore.getState().openForProject("B");
    created.resolve({ id: "CA" });
    await sending;
    expect(useChatStore.getState().conversationId).toBeNull();
    expect(useChatStore.getState().messages).toEqual([]);
    expect(streams).toHaveLength(0);
    expect(mock.sendMessage).toHaveBeenCalledWith("CA", "pour A", expect.anything());
  });

  it("ignores a late refetch from the previous project", async () => {
    mock.listConversations.mockResolvedValueOnce([{ id: "CA" }]);
    mock.listMessages.mockResolvedValueOnce([]);
    await useChatStore.getState().openForProject("A");
    const late = deferred<Array<{ id: string; role: string; content: string }>>();
    mock.listMessages.mockReturnValueOnce(late.promise);
    streams[0]?.handlers.onDone?.();
    mock.listConversations.mockResolvedValueOnce([{ id: "CB" }]);
    mock.listMessages.mockResolvedValueOnce([{ id: "b", role: "user", content: "B" }]);
    await useChatStore.getState().openForProject("B");
    late.resolve([{ id: "a", role: "user", content: "A" }]);
    await flush();
    expect(useChatStore.getState().messages.map((m) => m.content)).toEqual(["B"]);
  });

  it("does not start a stream once the page has closed", async () => {
    const list = deferred<Array<{ id: string }>>();
    mock.listConversations.mockReturnValue(list.promise);
    const opening = useChatStore.getState().openForProject("A");
    useChatStore.getState().close();
    list.resolve([{ id: "CA" }]);
    await opening;
    expect(streams).toHaveLength(0);
  });

  it("gives the text back and removes the bubble when sending fails", async () => {
    mock.listConversations.mockResolvedValue([{ id: "CA" }]);
    mock.listMessages.mockResolvedValue([]);
    await useChatStore.getState().openForProject("A");
    mock.sendMessage.mockRejectedValue(new Error("409"));
    await useChatStore.getState().send("mon long message");
    const state = useChatStore.getState();
    expect(state.failedDraft).toBe("mon long message");
    expect(state.messages).toEqual([]);
    expect(state.sending).toBe(false);
  });

  it.each([
    ["still waiting", [{ conversation_id: "CA", status: "todo" }], { count: 2 }],
    ["refused or already run", [{ conversation_id: "CA", status: "done" }], null],
  ])("re-offers a replayed plan only when %s", async (_label, tasks, expected) => {
    mock.listConversations.mockResolvedValue([{ id: "CA" }]);
    mock.listMessages.mockResolvedValue([]);
    mock.listTasks.mockResolvedValue(tasks);
    await useChatStore.getState().openForProject("A");
    const { handlers } = streams[0]!;
    handlers.onDecision?.({ kind: "plan_tasks", count: 2, summary: "", historical: true });
    handlers.onReplayEnd?.();
    await flush();
    expect(useChatStore.getState().pendingPlan).toEqual(expected);
  });
});
