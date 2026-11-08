"""Non-regression tests (preview, redaction, providers, MCP) from the 2026-11 audit."""

from __future__ import annotations

import http.client
import json
import os
import sys
import textwrap
import time
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from elysium_engine.db.models import Project
from elysium_engine.db.session import create_db_engine, create_session_factory, init_db
from elysium_engine.mcp.client import McpError, McpStdioClient
from elysium_engine.mcp.runtime import LaunchSpec, probe_server
from elysium_engine.parent_watch import pid_alive
from elysium_engine.preview.detect import detect
from elysium_engine.preview.manager import PreviewError, PreviewManager
from elysium_engine.preview.static_server import StaticPreviewServer
from elysium_engine.proctree import unsafe_shim_argument
from elysium_engine.providers.anthropic import AnthropicProvider
from elysium_engine.providers.base import ProviderError, default_client, is_private_url
from elysium_engine.providers.openai_compat import OpenAICompatProvider
from elysium_engine.providers.redaction import REDACTED, redact_secrets
from elysium_engine.providers.registry import ProviderSpec


def _symlink(target: Path, link: Path) -> None:
    try:
        os.symlink(target, link)
    except OSError:
        pytest.skip("creating symlinks needs a privilege this account does not have")


def _get(port: int, path: str) -> tuple[int, bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", path)
    response = conn.getresponse()
    return response.status, response.read()


@pytest.fixture
def static_site(tmp_path: Path):  # type: ignore[no-untyped-def]
    site = tmp_path / "site"
    (site / "folder").mkdir(parents=True)
    (site / "folder" / ".env").write_text("A=1")
    (site / "folder" / "a.txt").write_text("x")
    (site / "page").mkdir()
    (site / "page" / "index.html").write_text("<body>page</body>")
    (site / "index.html").write_text("<body>ok</body>")
    server = StaticPreviewServer(site.resolve())
    server.start()
    yield server, site, tmp_path
    server.stop()


def test_index_symlink_cannot_read_outside_the_project(static_site) -> None:  # type: ignore[no-untyped-def]
    server, site, tmp_path = static_site
    outside = tmp_path / "outside.html"
    outside.write_text("SECRET")
    (site / "leak").mkdir()
    _symlink(outside, site / "leak" / "index.html")
    status, body = _get(server.port, "/leak/")
    assert status == 404
    assert b"SECRET" not in body


def test_folder_listing_is_not_served(static_site) -> None:  # type: ignore[no-untyped-def]
    server, _, _ = static_site
    status, body = _get(server.port, "/folder/")
    assert status == 404
    assert b".env" not in body


def test_folder_without_slash_redirects_like_a_web_server(static_site) -> None:  # type: ignore[no-untyped-def]
    server, _, _ = static_site
    assert _get(server.port, "/page")[0] == 301
    assert b"page" in _get(server.port, "/page/")[1]


def test_nul_byte_gets_an_answer(static_site) -> None:  # type: ignore[no-untyped-def]
    server, _, _ = static_site
    assert _get(server.port, "/a%00.txt")[0] == 403


@pytest.mark.parametrize(
    "manifest",
    [
        '{"devDependencies":["x"]}',
        '{"dependencies":"vite"}',
        '{"dependencies":{"vite":"1"},"scripts":5}',
        '{"dependencies":{"vite":"1"},"scripts":"dev"}',
        '{"dependencies":{"vite":"1"},"scripts":{"dev":null}}',
        '{"dependencies":{"vite":"1"},"scripts":{"dev":"  "}}',
    ],
)
def test_malformed_manifest_is_reported_not_run(tmp_path: Path, manifest: str) -> None:
    (tmp_path / "package.json").write_text(manifest)
    assert not detect(tmp_path).runnable


def test_empty_manifest_is_not_called_invalid_json(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{}")
    (tmp_path / "index.html").write_text("x")
    assert detect(tmp_path).framework == "static"


@pytest.fixture
def previews(tmp_path: Path):  # type: ignore[no-untyped-def]
    engine = create_db_engine(f"sqlite:///{tmp_path}/p.db")
    init_db(engine)
    factory = create_session_factory(engine)
    with factory() as session:
        project = Project(name="x", description="")
        session.add(project)
        session.commit()
        project_id = project.id
    manager = PreviewManager(factory, opener=lambda _url: None)
    yield manager, project_id
    manager.stop_all()


def _vite_app(folder: Path, script: str) -> None:
    folder.mkdir(exist_ok=True)
    (folder / "node_modules").mkdir(exist_ok=True)
    (folder / "package.json").write_text(
        json.dumps({"dependencies": {"vite": "1"}, "scripts": {"dev": script}})
    )


def _grant_trust(manager: PreviewManager, project_id: str) -> None:
    """What start(trust=True) records, without running anything."""
    from elysium_engine.preview.detect import manifest_digest

    session = manager._sessions[project_id]
    session.trusted = True
    session.trust_digest = manifest_digest(session.detection)
    manager._persist(session)


def test_trust_is_lost_when_the_scripts_change(previews, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    manager, project_id = previews
    app = tmp_path / "app"
    _vite_app(app, "vite")
    manager.configure(project_id, str(app))
    _grant_trust(manager, project_id)
    assert manager.status(project_id)["needs_trust"] is False

    _vite_app(app, "node steal.js")
    manager._sessions.clear()  # also holds after an engine restart
    assert manager.status(project_id)["needs_trust"] is True
    with pytest.raises(PreviewError) as refused:
        manager.start(project_id)
    assert refused.value.code == "trust_required"


def test_static_project_that_gains_a_dev_server_needs_trust(previews, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    manager, project_id = previews
    app = tmp_path / "site"
    app.mkdir()
    (app / "index.html").write_text("x")
    assert manager.configure(project_id, str(app))["framework"] == "static"

    _vite_app(app, "vite")
    view = manager.status(project_id)
    assert view["framework"] != "static"
    assert view["needs_trust"] is True
    with pytest.raises(PreviewError):
        manager.start(project_id)


@pytest.mark.parametrize(
    "secret",
    [
        "wJalrXUtnFEMIK7MDENGbPxRfiCYEXAMPLEKEY",
        "hunter2hunter2",
        "S3cr3tP4ss",
        "dXNlcjpwYXNzd29yZA==",
        "abcdefgh12345678",
    ],
)
@pytest.mark.parametrize(
    "template",
    [
        "AWS_SECRET_ACCESS_KEY={}",
        "DB_PASSWORD={}",
        "access_token: {}",
        'client_secret = "{}"',
        "postgres://admin:{}@db.example/app",
        "https://user:{}@example.com/x",
    ],
)
def test_common_secret_shapes_are_redacted(template: str, secret: str) -> None:
    text = template.format(secret)
    assert secret not in redact_secrets(text)


@pytest.mark.parametrize(
    "text",
    [
        "Authorization: Basic dXNlcjpwYXNzd29yZA==",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.abcdefghijklmnopqrstuv",
        "sk_" + "live_abcdefghijklmnopqrstuvwx",  # split so scanners don't flag this fake
        "-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n",
        "-----BEGIN PGP PRIVATE KEY BLOCK-----\nabc\n-----END PGP PRIVATE KEY BLOCK-----",
    ],
)
def test_token_formats_are_redacted(text: str) -> None:
    assert redact_secrets(text) == REDACTED or text.split()[-1] not in redact_secrets(text)


def test_quoted_value_with_spaces_is_redacted() -> None:
    assert "battery" not in redact_secrets('password = "correct horse battery staple"')


def test_redaction_keeps_ordinary_text() -> None:
    for text in (
        "max_tokens=12345678",
        "input_tokens: 4096",
        "See https://example.com/docs:8080/page",
        "Le mot de passe est demandé à la connexion.",
    ):
        assert redact_secrets(text) == text


def test_redaction_keeps_json_valid() -> None:
    document = json.loads(redact_secrets(json.dumps({"password": "abcdefgh12345"})))
    assert document == {"password": REDACTED}


def test_redaction_stays_fast_on_huge_input() -> None:
    started = time.monotonic()
    redact_secrets("-----BEGIN PRIVATE KEY----- " * 20_000 + "a_b-c." * 200_000)
    assert time.monotonic() - started < 5


@pytest.mark.parametrize("value", ["m&calc", 'a"b', "a|b", "a>b", "a^b", "%PATH%", "a\nb"])
def test_batch_shim_refuses_shell_metacharacters(value: str) -> None:
    assert unsafe_shim_argument([r"C:\x\codex.CMD", "-m", value]) == value


def test_batch_shim_allows_ordinary_values_and_exe_anything() -> None:
    assert unsafe_shim_argument([r"C:\x\npx.cmd", "-y", "@s/server", "gpt-5.1:high"]) is None
    assert unsafe_shim_argument([r"C:\x\npx.cmd", "postgres://u:p%40ss@h/db"]) is None
    assert unsafe_shim_argument([r"C:\x\claude.exe", "a&b"]) is None


async def test_mcp_refuses_to_launch_an_injectable_batch_command() -> None:
    client = McpStdioClient([r"C:\x\npx.cmd", "x&calc"])
    with pytest.raises(McpError):
        await client.start()


@pytest.mark.parametrize(
    ("url", "private"),
    [
        ("http://localhost:11434/v1", True),
        ("http://127.0.0.1:1234", True),
        ("http://192.168.1.20:8000", True),
        ("http://gpu-box:8000", True),
        ("http://[::1]:8000", True),
        ("https://api.anthropic.com", False),
        ("https://ollama.example.com", False),
        ("http://8.8.8.8", False),
        ("", False),
    ],
)
def test_private_url(url: str, private: bool) -> None:
    assert is_private_url(url) is private


def _spec(base_url: str, is_local: bool) -> ProviderSpec:
    return ProviderSpec("x", "openai", base_url, is_local, "m", ())


def test_local_flag_alone_does_not_make_a_provider_local() -> None:
    assert _spec("https://evil.example/v1", True).stays_local is False
    assert _spec("http://localhost:11434/v1", True).stays_local is True
    assert _spec("http://localhost:11434/v1", False).stays_local is False


async def test_local_calls_ignore_proxy_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example:3128")
    monkeypatch.delenv("NO_PROXY", raising=False)
    async with default_client(trust_env=True) as proxied:
        assert proxied._mounts  # the variable is really honoured otherwise
    async with default_client(trust_env=False) as direct:
        assert not direct._mounts


def _anthropic(handler) -> AnthropicProvider:  # type: ignore[no-untyped-def]
    return AnthropicProvider(
        "k", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), default_model="m"
    )


def _openai(handler) -> OpenAICompatProvider:  # type: ignore[no-untyped-def]
    return OpenAICompatProvider(
        "k",
        name="o",
        base_url="https://o.example/v1",
        default_model="m",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


async def _drain(provider) -> list[dict]:  # type: ignore[no-untyped-def]
    return [c async for c in provider.chat([{"role": "user", "content": "x"}], stream=True)]


@pytest.mark.parametrize("build", [_anthropic, _openai])
@pytest.mark.parametrize("line", ["data: <html>proxy</html>", "data: [1,2]"])
async def test_garbage_stream_is_a_provider_error(build, line: str) -> None:  # type: ignore[no-untyped-def]
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=line + "\n\n")

    with pytest.raises(ProviderError):
        await _drain(build(handler))


@pytest.mark.parametrize("build", [_anthropic, _openai])
async def test_connection_failure_is_a_provider_error(build) -> None:  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(ProviderError):
        await _drain(build(handler))


async def test_truncated_anthropic_stream_is_not_a_complete_answer() -> None:
    delta = {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "a"}}

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=f"data: {json.dumps(delta)}\n\n")

    with pytest.raises(ProviderError):
        await _drain(_anthropic(handler))


async def test_deleting_a_server_removes_its_secrets(auth_client: AsyncClient, app: FastAPI) -> None:
    server = (await auth_client.post("/mcp/servers", json={"catalog_id": "github"})).json()
    await auth_client.patch(f"/mcp/servers/{server['id']}", json={"config": {"GITHUB_TOKEN": "t0k"}})
    key = f"mcp:{server['id']}:GITHUB_TOKEN"
    assert app.state.secret_store.get(key) == "t0k"
    await auth_client.delete(f"/mcp/servers/{server['id']}")
    assert app.state.secret_store.get(key) is None


def _fake_server(tmp_path: Path, body: str) -> LaunchSpec:
    script = tmp_path / "server.py"
    script.write_text(
        textwrap.dedent(
            """
            import json, subprocess, sys
            def reply(i, result):
                sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": i, "result": result}) + "\\n")
                sys.stdout.flush()
            """
        )
        + textwrap.dedent(body)
    )
    return LaunchSpec(argv=[sys.executable, str(script)])


async def test_invalid_tool_list_is_reported_not_a_crash(tmp_path: Path) -> None:
    spec = _fake_server(
        tmp_path,
        """
        for line in sys.stdin:
            message = json.loads(line)
            if message.get("method") == "initialize":
                reply(message["id"], {"serverInfo": "nope"})
            elif message.get("method") == "tools/list":
                reply(message["id"], {"tools": "nope"})
        """,
    )
    result = await probe_server(spec, startup_timeout_s=20)
    assert result.ok is False
    assert "invalid" in (result.error or "")


async def test_closing_a_server_also_stops_what_it_started(tmp_path: Path) -> None:
    marker = tmp_path / "child.pid"
    spec = _fake_server(
        tmp_path,
        f"""
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        open({str(marker)!r}, "w").write(str(child.pid))
        for line in sys.stdin:
            message = json.loads(line)
            if message.get("method") == "initialize":
                reply(message["id"], {{}})
        """,
    )
    client = McpStdioClient(spec.argv, startup_timeout_s=20)
    await client.start()
    child = int(marker.read_text())
    assert pid_alive(child)
    await client.close()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and pid_alive(child):
        time.sleep(0.1)
    assert not pid_alive(child)
