"""Expert "complet", stopping a run and agents using MCP tools.

The rule under test everywhere: a model only ever produces proposals and
requests. Nothing touches the disk or runs a tool without a human decision.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from elysium_engine.agents.base import EventLog
from elysium_engine.agents.orchestrator import _forced_model, run_expert_complete, run_expert_analysis
from elysium_engine.app_settings import default_settings
from elysium_engine.db.models import FileChange, MemoryFolder
from elysium_engine.db.repository import (
    AgentRepository,
    ConversationRepository,
    EventRepository,
    McpServerRepository,
    ProviderRepository,
    TaskRepository,
)
from elysium_engine.mcp.runtime import TOOLS_CACHE
from elysium_engine.mcp.toolbox import ActionGate, parse_tool_request
from elysium_engine.routing import ModelOption
from elysium_engine.workspace import (
    NotTextFileError,
    UnsafePathError,
    clean_relative_path,
    read_confined,
    sha256_text,
)


def _answer(text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"index": 0, "message": {"content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        },
    )


def _provider(app: FastAPI, handler) -> None:  # type: ignore[no-untyped-def]
    app.state.registry.chat_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with app.state.session_factory() as session:
        ProviderRepository(session).upsert(
            "openai", base_url="https://api.openai.com/v1", default_model="gpt-6-luna", is_local=False
        )
    app.state.secret_store.set("openai", "fake-key")


async def _project(auth_client: AsyncClient, app: FastAPI, root: Path | None = None) -> str:
    project_id = (await auth_client.post("/projects", json={"name": "P", "description": ""})).json()["id"]
    if root is not None:
        with app.state.session_factory() as session:
            session.add(MemoryFolder(project_id=project_id, root_path=str(root)))
            session.commit()
    return project_id


def _task(app: FastAPI, project_id: str, role: str = "backend", title: str = "Do it") -> str:
    with app.state.session_factory() as session:
        return TaskRepository(session).create(project_id, title, role).id


def _conversation(app: FastAPI, project_id: str) -> str:
    with app.state.session_factory() as session:
        return ConversationRepository(session).create(project_id).id


def _run_kwargs(app: FastAPI, project_id: str, conversation_id: str) -> dict[str, object]:
    settings = default_settings()
    settings.ai.streaming = False
    return {
        "session_factory": app.state.session_factory,
        "registry": app.state.registry,
        "event_log": EventLog(app.state.session_factory, app.state.event_bus),
        "project_id": project_id,
        "conversation_id": conversation_id,
        "app_settings": settings,
    }


def _events(app: FastAPI, conversation_id: str) -> list:  # type: ignore[type-arg]
    with app.state.session_factory() as session:
        rows = list(EventRepository(session).list_for_conversation(conversation_id))
        session.expunge_all()
    return rows


def _changes(app: FastAPI, project_id: str) -> list[FileChange]:
    with app.state.session_factory() as session:
        rows = list(session.query(FileChange).filter_by(project_id=project_id))
        session.expunge_all()
    return rows


# ------------------------------------------------------------------- paths


@pytest.mark.parametrize(
    "path",
    [
        "../outside.txt", "a/../../b", "/etc/passwd", "C:/Windows/x", "C:evil", "~/x", "a//b",
        ".git/config", "src/.GIT/hooks/pre-commit", ".git./config", ".env", "api/.env.production",
        "certs/server.pem", "id_rsa", "node_modules/x/index.js", "file.txt:stream", "CON", "aux.txt",
        "dir /x", "dir./x", "a\x00b", ".ssh/authorized_keys", "",
    ],
)
def test_a_dangerous_path_is_refused(path: str) -> None:
    with pytest.raises(UnsafePathError):
        clean_relative_path(path)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("src/app.ts", "src/app.ts"), ("src\\app.ts", "src/app.ts"), (".env.example", ".env.example"),
     (".github/ci.yml", ".github/ci.yml"), ("  a.txt ", "a.txt")],
)
def test_a_normal_path_is_kept(raw: str, expected: str) -> None:
    assert clean_relative_path(raw) == expected


def test_reading_keeps_the_exact_line_endings(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"one\r\ntwo\n")
    assert read_confined(tmp_path, "a.txt") == "one\r\ntwo\n"
    assert read_confined(tmp_path, "missing.txt") is None


def test_a_binary_file_is_not_reviewable(tmp_path: Path) -> None:
    (tmp_path / "a.bin").write_bytes(b"\xff\xfe\x00")
    with pytest.raises(NotTextFileError):
        read_confined(tmp_path, "a.bin")


def test_a_link_cannot_lead_outside(tmp_path: Path) -> None:
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir(), outside.mkdir()
    (outside / "secret.txt").write_text("s")
    try:
        (root / "link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks need a privilege on this machine")
    with pytest.raises(UnsafePathError):
        read_confined(root, "link/secret.txt")


# ------------------------------------------------------------- expert complet


async def test_complete_run_proposes_and_writes_nothing(
    app: FastAPI, auth_client: AsyncClient, tmp_path: Path
) -> None:
    (tmp_path / "app.py").write_bytes(b"old\r\n")
    (tmp_path / "gone.py").write_text("bye")
    reply = (
        'Done.\n<elysium-file path="app.py">\nnew\n</elysium-file>\n'
        '<elysium-file path="src/new.py">\nx = 1\n</elysium-file>\n'
        '<elysium-delete path="gone.py"/>\n'
        '<elysium-file path="../evil.py">\nboom\n</elysium-file>\n'
    )
    _provider(app, lambda r: _answer(reply))
    project_id = await _project(auth_client, app, tmp_path)
    task_id = _task(app, project_id)
    conversation_id = _conversation(app, project_id)

    await run_expert_complete(**_run_kwargs(app, project_id, conversation_id))

    # The disk is untouched.
    assert (tmp_path / "app.py").read_bytes() == b"old\r\n"
    assert (tmp_path / "gone.py").exists()
    assert not (tmp_path / "src").exists()
    assert not (tmp_path.parent / "evil.py").exists()

    by_path = {c.path: c for c in _changes(app, project_id)}
    assert set(by_path) == {"app.py", "src/new.py", "gone.py"}
    assert by_path["app.py"].base_content == "old\r\n"
    assert by_path["app.py"].base_sha256 == sha256_text("old\r\n")
    assert by_path["app.py"].new_content == "new\n"
    assert by_path["src/new.py"].base_sha256 is None
    assert by_path["gone.py"].action == "delete" and by_path["gone.py"].new_content is None

    events = _events(app, conversation_id)
    assert any("refused" in e.payload.get("message", "") for e in events if e.type == "error")
    done = next(e for e in events if e.type == "done")
    assert done.payload["kind"] == "expert_complete_summary"
    assert done.payload["changes_proposed"] == 3
    with app.state.session_factory() as session:
        task = TaskRepository(session).get(task_id)
        assert task is not None and task.status == "done"
        assert "elysium-file" not in (task.result_summary or "")


async def test_an_agent_without_write_permission_proposes_nothing(
    app: FastAPI, auth_client: AsyncClient, tmp_path: Path
) -> None:
    _provider(app, lambda r: _answer('<elysium-file path="a.py">\nx\n</elysium-file>\n'))
    project_id = await _project(auth_client, app, tmp_path)
    _task(app, project_id, role="architect")  # filesystem=read in the roster
    conversation_id = _conversation(app, project_id)
    await run_expert_complete(**_run_kwargs(app, project_id, conversation_id))
    assert _changes(app, project_id) == []
    assert any("permission" in e.payload.get("message", "") for e in _events(app, conversation_id))


async def test_filesystem_none_gives_no_file_content(
    app: FastAPI, auth_client: AsyncClient, tmp_path: Path
) -> None:
    (tmp_path / "topsecret.py").write_text("PAYLOAD_MARKER")
    prompts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        prompts.append(request.content.decode())
        return _answer("ok")

    _provider(app, handler)
    project_id = await _project(auth_client, app, tmp_path)
    with app.state.session_factory() as session:
        session.add_all([])
        from elysium_engine.db.models import FileNode

        session.add(FileNode(project_id=project_id, path="topsecret.py", summary="topsecret"))
        record = AgentRepository(session).get_by_role_or_name(project_id, "backend")
        assert record is not None
        record.filesystem = "none"
        session.commit()
    _task(app, project_id, title="topsecret work")
    await run_expert_complete(**_run_kwargs(app, project_id, _conversation(app, project_id)))
    assert prompts and all("PAYLOAD_MARKER" not in p for p in prompts)


async def test_a_later_task_sees_what_an_earlier_one_proposed(
    app: FastAPI, auth_client: AsyncClient, tmp_path: Path
) -> None:
    prompts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        prompts.append(request.content.decode())
        if len(prompts) == 1:
            return _answer('<elysium-file path="shared.py">\nFIRST_PROPOSAL\n</elysium-file>\n')
        return _answer('<elysium-file path="shared.py">\nSECOND\n</elysium-file>\n')

    _provider(app, handler)
    project_id = await _project(auth_client, app, tmp_path)
    with app.state.session_factory() as session:
        repo = TaskRepository(session)
        first = repo.create(project_id, "one", "backend")
        repo.create(project_id, "two", "backend", depends_on=[first.id])
    await run_expert_complete(**_run_kwargs(app, project_id, _conversation(app, project_id)))
    assert "FIRST_PROPOSAL" in prompts[1]
    # Same file twice in one run: one review, the latest content.
    changes = _changes(app, project_id)
    assert len(changes) == 1 and changes[0].new_content == "SECOND\n"


async def test_review_states_are_enforced(app: FastAPI, auth_client: AsyncClient, tmp_path: Path) -> None:
    project_id = await _project(auth_client, app, tmp_path)
    with app.state.session_factory() as session:
        change = FileChange(project_id=project_id, path="a.py", new_content="x\n", agent_name="backend")
        session.add(change)
        session.commit()
        change_id = change.id

    listed = (await auth_client.get(f"/projects/{project_id}/changes")).json()
    assert [c["id"] for c in listed] == [change_id] and "new_content" not in listed[0]
    detail = (await auth_client.get(f"/changes/{change_id}")).json()
    assert detail["new_sha256"] == sha256_text("x\n") and detail["base_sha256"] is None

    post = lambda s: auth_client.post(f"/changes/{change_id}/status", json={"status": s})  # noqa: E731
    assert (await post("reverted")).status_code == 409  # not applied yet
    assert (await post("sorcery")).status_code == 422
    assert (await post("applied")).status_code == 200
    assert (await post("rejected")).status_code == 409
    assert (await post("reverted")).status_code == 200
    assert (await auth_client.get(f"/projects/{project_id}/workspace")).json()["root_path"] == str(tmp_path)


async def test_expert_plan_turn_makes_a_plan(app: FastAPI, auth_client: AsyncClient) -> None:
    _provider(app, lambda r: _answer("The plan."))
    project_id = await _project(auth_client, app)
    conversation_id = _conversation(app, project_id)
    response = await auth_client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": "plan", "mode": "plan", "execution": "expert", "expert_submode": "analyse"},
    )
    assert response.status_code == 202
    run = app.state.active_runs.get(conversation_id)
    if run is not None:
        await run
    messages = (await auth_client.get(f"/conversations/{conversation_id}/messages")).json()
    assert messages[-1]["role"] == "assistant"
    assert not any("No task graph" in e.payload.get("message", "") for e in _events(app, conversation_id))


def test_forced_model_rules() -> None:
    ai = default_settings().ai
    option = ModelOption(
        provider="openai", model="m", tier="balanced", context_window=1000, input_cost=1, output_cost=1
    )
    assert _forced_model("anthropic:x:y", ai, []) == ("anthropic", "x:y")
    ai.default_provider, ai.default_model, ai.auto_routing = "openai", "m", True
    assert _forced_model(None, ai, [option]) is None  # routing stays on
    ai.auto_routing = False
    assert _forced_model(None, ai, [option]) == ("openai", "m")
    assert _forced_model(None, ai, []) is None


async def test_expert_honours_effort_and_language(
    app: FastAPI, auth_client: AsyncClient
) -> None:
    bodies: list[dict] = []  # type: ignore[type-arg]

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return _answer("fine")

    _provider(app, handler)
    project_id = await _project(auth_client, app)
    _task(app, project_id)
    kwargs = _run_kwargs(app, project_id, _conversation(app, project_id))
    kwargs["app_settings"].general.ai_response_language = "es"  # type: ignore[attr-defined]
    await run_expert_analysis(**kwargs, effort="high")  # type: ignore[arg-type]
    assert "Spanish" in json.dumps(bodies[0])


# ------------------------------------------------------------------- cancel


async def test_cancel_stops_a_run_and_keeps_the_board_clean(
    app: FastAPI, auth_client: AsyncClient
) -> None:
    started = asyncio.Event()

    async def hanging(request: httpx.Request) -> httpx.Response:
        started.set()
        await asyncio.sleep(60)
        return _answer("never")

    _provider(app, hanging)
    project_id = await _project(auth_client, app)
    task_id = _task(app, project_id)
    conversation_id = _conversation(app, project_id)
    response = await auth_client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": "go", "execution": "expert", "expert_submode": "analyse"},
    )
    assert response.status_code == 202
    await asyncio.wait_for(started.wait(), 5)

    cancelled = await auth_client.post(f"/conversations/{conversation_id}/cancel")
    assert cancelled.json() == {"cancelled": True}
    with app.state.session_factory() as session:
        task = TaskRepository(session).get(task_id)
        assert task is not None and task.status == "todo"
    assert _events(app, conversation_id)[-1].payload["kind"] == "cancelled"
    # A new message is accepted: nothing stays locked.
    assert (await auth_client.post(f"/conversations/{conversation_id}/cancel")).json() == {"cancelled": False}


async def test_cancel_unknown_conversation_is_404(auth_client: AsyncClient) -> None:
    assert (await auth_client.post("/conversations/nope/cancel")).status_code == 404


# ---------------------------------------------------------------------- MCP

FAKE_SERVER = r"""
import json, sys
for line in sys.stdin:
    m = json.loads(line)
    if "id" not in m: continue
    if m["method"] == "initialize":
        r = {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "fake"}}
    elif m["method"] == "tools/call":
        r = {"content": [{"type": "text", "text": "TOOL_OUTPUT:" + m["params"]["arguments"]["q"]}]}
    else:
        r = {"tools": []}
    print(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": r}), flush=True)
"""


def _install_server(app: FastAPI, tmp_path: Path, enabled: bool = True) -> None:
    script = tmp_path / "fake_mcp.py"
    script.write_text(FAKE_SERVER)
    with app.state.session_factory() as session:
        repo = McpServerRepository(session)
        server = repo.create(
            name="fake", url_or_command=f'"{sys.executable}" "{script}"', transport="stdio"
        )
        repo.update(
            server,
            enabled=enabled,
            config={TOOLS_CACHE: [{"name": "search", "description": "Search things"}]},
        )


def _grant_network(app: FastAPI, project_id: str) -> None:
    with app.state.session_factory() as session:
        record = AgentRepository(session).get_by_role_or_name(project_id, "backend")
        assert record is not None
        record.network = True
        session.commit()


def test_parse_tool_request() -> None:
    ok = parse_tool_request('<elysium-tool server="s" name="t">{"a": 1}</elysium-tool>')
    assert ok is not None and not isinstance(ok, str) and ok.arguments == {"a": 1}
    assert parse_tool_request("no block") is None
    assert isinstance(parse_tool_request('<elysium-tool server="s" name="t">[1]</elysium-tool>'), str)
    assert isinstance(parse_tool_request('<elysium-tool server="s" name="t">{oops</elysium-tool>'), str)


async def test_gate_times_out_as_a_refusal() -> None:
    gate = ActionGate()
    assert await gate.request("a", "c", {}, 0.01) is False
    assert gate.pending_for("c") == []


async def _mcp_run(
    app: FastAPI,
    project_id: str,
    conversation_id: str,
    decide: bool | None,
    gate: ActionGate,
) -> None:
    run = asyncio.create_task(
        run_expert_analysis(
            **_run_kwargs(app, project_id, conversation_id),  # type: ignore[arg-type]
            gate=gate,
            secret_store=app.state.secret_store,
        )
    )
    if decide is not None:
        for _ in range(500):
            pending = gate.pending_for(conversation_id)
            if pending:
                assert gate.resolve("other-id", conversation_id, True) is False
                assert gate.resolve(pending[0]["action_id"], "other-conversation", True) is False
                assert gate.resolve(pending[0]["action_id"], conversation_id, decide) is True
                break
            await asyncio.sleep(0.01)
        else:
            run.cancel()
            pytest.fail("no action was requested")
    await asyncio.wait_for(run, 30)


def _tool_scripted(prompts: list[str]):  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        prompts.append(request.content.decode())
        if len(prompts) == 1:
            return _answer('<elysium-tool server="fake" name="search">{"q": "abc"}</elysium-tool>')
        return _answer("finished")

    return handler


async def test_an_approved_tool_runs_for_real(app: FastAPI, auth_client: AsyncClient, tmp_path: Path) -> None:
    prompts: list[str] = []
    _provider(app, _tool_scripted(prompts))
    _install_server(app, tmp_path)
    project_id = await _project(auth_client, app)
    _grant_network(app, project_id)
    task_id = _task(app, project_id)
    conversation_id = _conversation(app, project_id)

    await _mcp_run(app, project_id, conversation_id, True, ActionGate())

    assert "TOOL_OUTPUT:abc" in prompts[1]
    kinds = [e.payload.get("kind") for e in _events(app, conversation_id)]
    assert "tool_used" in kinds
    with app.state.session_factory() as session:
        task = TaskRepository(session).get(task_id)
        assert task is not None and task.status == "done" and task.result_summary == "finished"


async def test_a_refused_tool_never_runs(app: FastAPI, auth_client: AsyncClient, tmp_path: Path) -> None:
    prompts: list[str] = []
    _provider(app, _tool_scripted(prompts))
    _install_server(app, tmp_path)
    project_id = await _project(auth_client, app)
    _grant_network(app, project_id)
    _task(app, project_id)
    conversation_id = _conversation(app, project_id)
    await _mcp_run(app, project_id, conversation_id, False, ActionGate())
    assert "TOOL_OUTPUT" not in prompts[1] and "did not approve" in prompts[1]
    assert "tool_denied" in [e.payload.get("kind") for e in _events(app, conversation_id)]


async def test_without_network_permission_no_tool_is_offered(
    app: FastAPI, auth_client: AsyncClient, tmp_path: Path
) -> None:
    prompts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        prompts.append(request.content.decode())
        return _answer("done")

    _provider(app, handler)
    _install_server(app, tmp_path)
    project_id = await _project(auth_client, app)
    _task(app, project_id)
    await _mcp_run(app, project_id, _conversation(app, project_id), None, ActionGate())
    assert all("elysium-tool" not in p for p in prompts)


async def test_a_disabled_server_is_not_offered(
    app: FastAPI, auth_client: AsyncClient, tmp_path: Path
) -> None:
    prompts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        prompts.append(request.content.decode())
        return _answer("done")

    _provider(app, handler)
    _install_server(app, tmp_path, enabled=False)
    project_id = await _project(auth_client, app)
    _grant_network(app, project_id)
    _task(app, project_id)
    await _mcp_run(app, project_id, _conversation(app, project_id), None, ActionGate())
    assert all("elysium-tool" not in p for p in prompts)


async def test_tools_cache_stays_out_of_the_api(app: FastAPI, auth_client: AsyncClient, tmp_path: Path) -> None:
    _install_server(app, tmp_path)
    servers = (await auth_client.get("/mcp/servers")).json()
    assert servers and all(TOOLS_CACHE not in s["config"] for s in servers)


async def test_action_routes(app: FastAPI, auth_client: AsyncClient) -> None:
    project_id = await _project(auth_client, app)
    conversation_id = _conversation(app, project_id)
    assert (await auth_client.get(f"/conversations/{conversation_id}/actions")).json() == []
    missing = await auth_client.post(f"/conversations/{conversation_id}/actions/x", json={"approved": True})
    assert missing.status_code == 404


async def test_archiving_stops_the_preview(app: FastAPI, auth_client: AsyncClient) -> None:
    project_id = await _project(auth_client, app)
    stopped: list[str] = []
    app.state.previews.stop = lambda pid: stopped.append(pid)  # type: ignore[method-assign]
    assert (await auth_client.delete(f"/projects/{project_id}")).status_code == 204
    assert stopped == [project_id]
