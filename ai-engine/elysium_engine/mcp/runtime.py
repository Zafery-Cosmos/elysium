"""Turn an installed MCP server row into a runnable process, and test it.

``url_or_command`` holds the launch command (e.g. ``npx -y @scope/server <dossier>``).
``<placeholders>`` in it are filled from the server's configuration, and every
configuration field is also exported as an environment variable (secrets come
from the OS keychain, never the database).
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from elysium_engine.mcp.catalog import ConfigField
from elysium_engine.mcp.client import McpError, McpStdioClient, McpTool

# Servers that expect a different variable name than our form field key.
ENV_ALIASES: dict[str, str] = {
    "GITHUB_TOKEN": "GITHUB_PERSONAL_ACCESS_TOKEN",
    "GITLAB_TOKEN": "GITLAB_PERSONAL_ACCESS_TOKEN",
    "NOTION_API_KEY": "NOTION_TOKEN",
}

_PLACEHOLDER = re.compile(r"^<[^>]+>$")

_RUNTIME_HINTS = {
    "npx": "Node.js n'est pas installé (commande « npx » introuvable). Installez Node.js 20+ depuis nodejs.org.",
    "node": "Node.js n'est pas installé. Installez Node.js 20+ depuis nodejs.org.",
    "uvx": "« uv » n'est pas installé (commande « uvx » introuvable). Installez-le depuis docs.astral.sh/uv.",
    "uv": "« uv » n'est pas installé. Installez-le depuis docs.astral.sh/uv.",
    "docker": "Docker n'est pas installé ou pas démarré (commande « docker » introuvable).",
}


def _split_command(command: str) -> list[str]:
    """Split a command line. POSIX rules would eat the backslashes of Windows paths
    (``C:\\Program Files\\...``), so Windows uses the literal rules and unquotes."""
    if os.name != "nt":
        return shlex.split(command, posix=True)
    return [
        t[1:-1] if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'" else t
        for t in shlex.split(command, posix=False)
    ]


class McpConfigError(McpError):
    """The server cannot be launched yet (missing runtime or configuration)."""


@dataclass(frozen=True, slots=True)
class LaunchSpec:
    argv: list[str]
    env: dict[str, str] = field(default_factory=dict)


def build_launch(
    command: str,
    schema: tuple[ConfigField, ...],
    config: Mapping[str, Any],
    secrets: Mapping[str, str],
) -> LaunchSpec:
    """Resolve ``command`` + configuration into an argv and an environment."""
    if re.match(r"^https?://", command.strip()):
        raise McpConfigError(
            "Les serveurs MCP distants (adresse http) ne sont pas encore pris en charge ; "
            "utilisez une commande locale (par ex. « npx -y mcp-remote <url> »)."
        )
    try:
        parts = _split_command(command)
    except ValueError as exc:
        raise McpConfigError(f"Commande invalide : {exc}") from exc
    if not parts:
        raise McpConfigError("Aucune commande de lancement n'est définie.")

    values: dict[str, str] = {}
    for f in schema:
        raw = secrets.get(f.key) if f.type == "secret" else config.get(f.key)
        if raw not in (None, ""):
            values[f.key] = str(raw)

    # <placeholder> arguments take the first non-secret configuration value.
    fillers = [f for f in schema if f.type != "secret"]
    argv: list[str] = []
    used = 0
    for token in parts:
        if _PLACEHOLDER.match(token):
            if used >= len(fillers):
                raise McpConfigError(f"Argument à renseigner : {token}")
            field_ = fillers[used]
            used += 1
            if field_.key not in values:
                raise McpConfigError(f"Renseignez d'abord « {field_.label} ».")
            argv.append(values[field_.key])
        else:
            argv.append(token)

    missing = [f.label for f in schema if f.required and f.key not in values]
    if missing:
        raise McpConfigError("Renseignez d'abord : " + ", ".join(f"« {m} »" for m in missing) + ".")

    exe = argv[0]
    resolved = shutil.which(exe)
    if resolved is None:
        raise McpConfigError(_RUNTIME_HINTS.get(exe, f"Commande introuvable : {exe}."))
    argv[0] = resolved

    env = {ENV_ALIASES.get(k, k): v for k, v in values.items()}
    env.update({k: v for k, v in values.items() if k not in env})
    return LaunchSpec(argv=argv, env=env)


@dataclass(frozen=True, slots=True)
class McpTestResult:
    ok: bool
    tools: list[McpTool] = field(default_factory=list)
    server_name: str | None = None
    server_version: str | None = None
    error: str | None = None
    duration_ms: int = 0


async def probe_server(spec: LaunchSpec, *, startup_timeout_s: float = 90.0) -> McpTestResult:
    """Start the server, run the handshake, list its tools, stop it."""
    started = time.monotonic()
    client = McpStdioClient(spec.argv, env=spec.env, startup_timeout_s=startup_timeout_s)
    try:
        await client.start()
        tools = await client.list_tools()
        info = client.server_info
        return McpTestResult(
            ok=True,
            tools=tools,
            server_name=info.get("name"),
            server_version=info.get("version"),
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    except McpError as exc:
        return McpTestResult(
            ok=False, error=str(exc), duration_ms=int((time.monotonic() - started) * 1000)
        )
    finally:
        await client.close()
