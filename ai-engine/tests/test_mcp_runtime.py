"""MCP runtime: the client protocol, launch resolution and the /test endpoint.

A tiny Python script plays the MCP server (newline-delimited JSON-RPC), so no
third-party package is ever executed by the test suite.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from elysium_engine.mcp.catalog import ConfigField
from elysium_engine.mcp.client import McpError, McpStdioClient, safe_environment
from elysium_engine.mcp.runtime import LaunchSpec, McpConfigError, build_launch, probe_server

FAKE_SERVER = r'''
import json, sys
print("starting up (banner on stdout, must be ignored)")
sys.stderr.write("log line on stderr\n"); sys.stderr.flush()
TOOLS = [{"name": "echo", "description": "Echo text", "inputSchema": {"type": "object"}},
         {"name": "add", "description": "Add numbers", "inputSchema": {"type": "object"}}]
for line in sys.stdin:
    if not line.strip().startswith("{"):
        continue
    msg = json.loads(line)
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:
        continue                                       # notification
    if method == "initialize":
        out = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
               "serverInfo": {"name": "fake-mcp", "version": "9.9"}}
    elif method == "tools/list":
        cur = (msg.get("params") or {}).get("cursor")  # two pages
        out = {"tools": TOOLS[:1], "nextCursor": "p2"} if not cur else {"tools": TOOLS[1:]}
    elif method == "tools/call":
        args = msg["params"]["arguments"]
        out = {"content": [{"type": "text", "text": args.get("text", "")}]}
    else:
        print(json.dumps({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "nope"}}), flush=True)
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": mid, "result": out}), flush=True)
'''

CRASHING_SERVER = "import sys; sys.stderr.write('boom: missing token'); sys.exit(3)"


@pytest.fixture
def fake_server(tmp_path: Path) -> list[str]:
    script = tmp_path / "fake_mcp.py"
    script.write_text(FAKE_SERVER, encoding="utf-8")
    return [sys.executable, str(script)]


# ------------------------------------------------------------------- client


async def test_client_handshake_lists_paginated_tools_and_calls_one(fake_server) -> None:  # type: ignore[no-untyped-def]
    client = McpStdioClient(fake_server, startup_timeout_s=20)
    try:
        await client.start()
        assert client.server_info["name"] == "fake-mcp"
        tools = await client.list_tools()
        assert [t.name for t in tools] == ["echo", "add"]  # both pages
        result = await client.call_tool("echo", {"text": "bonjour"})
        assert result["content"][0]["text"] == "bonjour"
    finally:
        await client.close()


async def test_client_reports_server_errors(fake_server) -> None:  # type: ignore[no-untyped-def]
    client = McpStdioClient(fake_server, startup_timeout_s=20)
    try:
        await client.start()
        with pytest.raises(McpError, match="nope"):
            await client._request("does/not/exist", {})
    finally:
        await client.close()


async def test_a_crashing_server_surfaces_its_stderr(tmp_path: Path) -> None:
    script = tmp_path / "crash.py"
    script.write_text(CRASHING_SERVER, encoding="utf-8")
    client = McpStdioClient([sys.executable, str(script)], startup_timeout_s=15)
    try:
        with pytest.raises(McpError, match="boom: missing token"):
            await client.start()
    finally:
        await client.close()


async def test_missing_binary_is_a_clear_error() -> None:
    with pytest.raises(McpError, match="cannot start"):
        await McpStdioClient(["definitely-not-a-real-binary-xyz"]).start()


def test_server_does_not_inherit_the_users_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "super-secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-xxx")
    env = safe_environment({"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_given_on_purpose"})
    assert "AWS_SECRET_ACCESS_KEY" not in env and "ANTHROPIC_API_KEY" not in env
    assert env["GITHUB_PERSONAL_ACCESS_TOKEN"] == "ghp_given_on_purpose"
    assert any(k.upper() == "PATH" for k in env)  # still able to run


# ------------------------------------------------------------------- launch


@pytest.fixture(autouse=True)
def _all_runners_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    # Pretend every runner (npx, uvx, docker) is installed; real absolute paths stay as-is.
    monkeypatch.setattr(
        "elysium_engine.mcp.runtime.shutil.which",
        lambda exe: exe if Path(exe).is_absolute() else f"/bin/{exe}",
    )


FS =(ConfigField("ROOT_PATH", "Dossier racine autorisé", "string"),)


def test_placeholder_is_filled_from_the_configuration() -> None:
    spec = build_launch("npx -y @modelcontextprotocol/server-filesystem <dossier>", FS,
                        {"ROOT_PATH": "/home/me/projet"}, {})
    assert spec.argv[1:] == ["-y", "@modelcontextprotocol/server-filesystem", "/home/me/projet"]


def test_missing_configuration_names_the_field_to_fill() -> None:
    with pytest.raises(McpConfigError, match="Dossier racine autorisé"):
        build_launch("npx -y server-filesystem <dossier>", FS, {}, {})


def test_secrets_come_from_the_keychain_and_use_the_servers_variable_name() -> None:
    schema = (ConfigField("GITHUB_TOKEN", "Jeton GitHub", "secret"),)
    spec = build_launch("npx -y @modelcontextprotocol/server-github", schema, {},
                        {"GITHUB_TOKEN": "ghp_abc"})
    assert spec.env["GITHUB_PERSONAL_ACCESS_TOKEN"] == "ghp_abc"  # what the server reads


def test_optional_fields_may_stay_empty() -> None:
    schema = (ConfigField("HF_TOKEN", "Jeton", "secret", required=False),)
    assert build_launch("npx -y some-server", schema, {}, {}).argv[0] == "/bin/npx"


def test_missing_runtime_gives_an_install_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("elysium_engine.mcp.runtime.shutil.which", lambda exe: None)
    with pytest.raises(McpConfigError, match="Node.js"):
        build_launch("npx -y some-server", (), {}, {})
    with pytest.raises(McpConfigError, match="uv"):
        build_launch("uvx some-server", (), {}, {})
    with pytest.raises(McpConfigError, match="Docker"):
        build_launch("docker run -i --rm img", (), {}, {})


def test_remote_http_servers_are_refused_with_an_explanation() -> None:
    with pytest.raises(McpConfigError, match="mcp-remote"):
        build_launch("https://example.com/mcp", (), {}, {})


def test_windows_style_paths_in_a_command_survive_splitting() -> None:
    from elysium_engine.mcp.runtime import _split_command

    if sys.platform == "win32":
        parts = _split_command(r'"C:\Program Files\nodejs\node.exe" C:\srv\index.js')
        assert parts == [r"C:\Program Files\nodejs\node.exe", r"C:\srv\index.js"]


# -------------------------------------------------------------------- probe


async def test_probe_server_reports_tools(fake_server) -> None:  # type: ignore[no-untyped-def]
    result = await probe_server(LaunchSpec(argv=fake_server), startup_timeout_s=20)
    assert result.ok and result.server_name == "fake-mcp"
    assert [t.name for t in result.tools] == ["echo", "add"]


async def test_probe_server_reports_a_failure_instead_of_raising(tmp_path: Path) -> None:
    script = tmp_path / "crash.py"
    script.write_text(CRASHING_SERVER, encoding="utf-8")
    result = await probe_server(LaunchSpec(argv=[sys.executable, str(script)]), startup_timeout_s=15)
    assert not result.ok and "boom: missing token" in (result.error or "")


# ------------------------------------------------------------------ endpoint


async def test_test_endpoint_really_starts_the_server(auth_client, fake_server) -> None:  # type: ignore[no-untyped-def]
    command = " ".join(f'"{p}"' for p in fake_server)
    created = await auth_client.post(
        "/mcp/servers", json={"name": "Fake", "url_or_command": command, "transport": "stdio"}
    )
    assert created.status_code == 201
    body = (await auth_client.post(f"/mcp/servers/{created.json()['id']}/test")).json()
    assert body["ok"] is True and body["server_name"] == "fake-mcp"
    assert [t["name"] for t in body["tools"]] == ["echo", "add"]


async def test_test_endpoint_explains_missing_configuration(auth_client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("elysium_engine.mcp.runtime.shutil.which", lambda exe: f"/bin/{exe}")
    created = await auth_client.post("/mcp/servers", json={"catalog_id": "filesystem"})
    body = (await auth_client.post(f"/mcp/servers/{created.json()['id']}/test")).json()
    assert body["ok"] is False and "Dossier racine" in body["error"]


async def test_test_endpoint_404(auth_client) -> None:  # type: ignore[no-untyped-def]
    assert (await auth_client.post("/mcp/servers/nope/test")).status_code == 404
