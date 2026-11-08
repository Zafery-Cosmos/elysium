"""MCP tools for agents: every single call waits for a human decision.

Models signal a call with a text block, so this works with every provider,
subscription CLIs included:

    <elysium-tool server="github" name="search_issues">{"q": "bug"}</elysium-tool>

The run then pauses on an ``action_request`` event.  Nothing starts until the
user accepts, a refusal or a timeout is reported back to the model, and only
tools listed by the server's last successful test can be requested.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from elysium_engine.agents.base import Agent, EventLog
from elysium_engine.db.models import McpServer, new_id
from elysium_engine.db.repository import McpServerRepository
from elysium_engine.mcp.client import McpError, McpStdioClient
from elysium_engine.mcp.runtime import LaunchSpec, cached_tools, launch_for
from elysium_engine.providers.redaction import redact_secrets
from elysium_engine.secrets import SecretStore
from elysium_engine.untrusted import data_block, one_line

log = logging.getLogger(__name__)

APPROVAL_TIMEOUT_S = 600.0
_TOOL_TIMEOUT_S = 120.0
_MAX_RESULT_CHARS = 20_000
_MAX_TOOLS_LISTED = 60
_MAX_ARGUMENT_CHARS = 20_000
_TOOL_BLOCK = re.compile(
    r'^<elysium-tool server="([^"\r\n]{1,200})" name="([^"\r\n]{1,200})">(.*?)</elysium-tool>[ \t]*$',
    re.MULTILINE | re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class ToolRequest:
    server: str
    tool: str
    arguments: dict[str, Any]


def parse_tool_request(text: str) -> ToolRequest | str | None:
    """The first tool block: a request, an error message for the model, or None."""
    match = _TOOL_BLOCK.search(text)
    if match is None:
        return None
    raw = match.group(3).strip() or "{}"
    if len(raw) > _MAX_ARGUMENT_CHARS:
        return "The tool arguments are too long."
    try:
        arguments = json.loads(raw)
    except ValueError:
        return "The tool arguments were not valid JSON. Send one JSON object."
    if not isinstance(arguments, dict):
        return "The tool arguments must be one JSON object."
    return ToolRequest(server=match.group(1), tool=match.group(2), arguments=arguments)


def strip_tool_blocks(text: str) -> str:
    return _TOOL_BLOCK.sub("", text).strip()


@dataclass(slots=True)
class PendingAction:
    id: str
    conversation_id: str
    payload: dict[str, Any]
    future: asyncio.Future[bool]


class ActionGate:
    """Actions waiting for the user. A refused or unanswered action never runs."""

    def __init__(self) -> None:
        self._pending: dict[str, PendingAction] = {}

    def pending_for(self, conversation_id: str) -> list[dict[str, Any]]:
        return [
            action.payload
            for action in self._pending.values()
            if action.conversation_id == conversation_id
        ]

    def resolve(self, action_id: str, conversation_id: str, approved: bool) -> bool:
        action = self._pending.get(action_id)
        if action is None or action.conversation_id != conversation_id or action.future.done():
            return False
        action.future.set_result(approved)
        return True

    async def request(
        self, action_id: str, conversation_id: str, payload: dict[str, Any], timeout_s: float
    ) -> bool:
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._pending[action_id] = PendingAction(action_id, conversation_id, payload, future)
        try:
            return await asyncio.wait_for(future, timeout_s)
        except asyncio.TimeoutError:
            return False
        finally:
            self._pending.pop(action_id, None)


def _result_text(result: Mapping[str, Any]) -> str:
    parts = [
        str(item.get("text", ""))
        for item in result.get("content") or []
        if isinstance(item, dict) and item.get("type") == "text"
    ]
    text = "\n".join(parts) or json.dumps(result, ensure_ascii=False)
    if len(text) > _MAX_RESULT_CHARS:
        text = f"{text[:_MAX_RESULT_CHARS]}\n[… result cut for size …]"
    return text


class McpToolbox:
    """What one run may call. Clients start on first approved use, and stop with the run."""

    def __init__(
        self,
        *,
        servers: dict[str, tuple[McpServer, set[str]]],
        descriptions: list[str],
        store: SecretStore,
        gate: ActionGate,
        event_log: EventLog,
        approval_timeout_s: float = APPROVAL_TIMEOUT_S,
    ) -> None:
        self._servers = servers
        self._descriptions = descriptions
        self._store = store
        self._gate = gate
        self._event_log = event_log
        self._approval_timeout_s = approval_timeout_s
        self._clients: dict[str, McpStdioClient] = {}

    @classmethod
    def load(
        cls,
        session_factory: sessionmaker[Session],
        store: SecretStore,
        gate: ActionGate,
        event_log: EventLog,
        approval_timeout_s: float = APPROVAL_TIMEOUT_S,
    ) -> "McpToolbox":
        servers: dict[str, tuple[McpServer, set[str]]] = {}
        descriptions: list[str] = []
        with session_factory() as session:
            for server in McpServerRepository(session).list():
                tools = cached_tools(server)
                if not server.enabled or not tools:
                    continue
                session.expunge(server)
                servers[server.name] = (server, {str(t.get("name", "")) for t in tools})
                descriptions += [
                    f"- server {one_line(server.name)!r}, tool {one_line(str(t.get('name', '')))!r}: "
                    f"{one_line(str(t.get('description', '')))[:300]}"
                    for t in tools
                ]
        return cls(
            servers=servers,
            descriptions=descriptions[:_MAX_TOOLS_LISTED],
            store=store,
            gate=gate,
            event_log=event_log,
            approval_timeout_s=approval_timeout_s,
        )

    @property
    def available(self) -> bool:
        return bool(self._servers)

    def instructions(self) -> str:
        return (
            "\n\nEXTERNAL TOOLS. You may ask to run one tool at a time. Output only this block "
            "and stop; the user approves each call and you then receive the result:\n"
            '<elysium-tool server="SERVER" name="TOOL">{"arg": "value"}</elysium-tool>\n'
            "Use a tool only when the task really needs it. Available tools:\n"
            + data_block("\n".join(self._descriptions))
        )

    def _emit(self, conversation_id: str, type_: str, payload: dict[str, Any], agent: str) -> None:
        self._event_log.append(conversation_id, type_, payload, agent)

    async def execute(self, request: ToolRequest, agent: Agent, conversation_id: str) -> str:
        """Run a requested tool once a human agreed; the outcome is text for the model."""
        known = self._servers.get(request.server)
        if not agent.network:
            return "Refused: your permissions do not include external tools."
        if known is None or request.tool not in known[1]:
            return f"Refused: no tool named '{request.tool}' on server '{request.server}'."

        action_id = new_id()
        shown = redact_secrets(json.dumps(request.arguments, ensure_ascii=False, indent=1))
        payload: dict[str, Any] = {
            "action_id": action_id,
            "agent": agent.name,
            "action": "mcp_tool",
            "tool": request.tool,
            "server": request.server,
            "arguments": shown,
            "status": "pending_approval",
            "summary": f"{request.server} › {request.tool}",
        }
        self._emit(conversation_id, "action_request", payload, agent.name)
        approved = await self._gate.request(
            action_id, conversation_id, payload, self._approval_timeout_s
        )
        decision = {
            "agent": agent.name,
            "action_id": action_id,
            "tool": request.tool,
            "server": request.server,
        }
        if not approved:
            self._emit(conversation_id, "decision", {**decision, "kind": "tool_denied"}, agent.name)
            return "The user did not approve this call. Continue without this tool."
        try:
            client = await self._client(request.server, known[0])
            result = await asyncio.wait_for(
                client.call_tool(request.tool, request.arguments), _TOOL_TIMEOUT_S
            )
        except (McpError, asyncio.TimeoutError) as exc:
            self._emit(conversation_id, "decision", {**decision, "kind": "tool_failed"}, agent.name)
            return f"The tool failed: {exc or 'timeout'}"
        self._emit(conversation_id, "decision", {**decision, "kind": "tool_used"}, agent.name)
        prefix = "The tool reported an error:\n" if result.get("isError") else ""
        return prefix + _result_text(result)

    async def _client(self, name: str, server: McpServer) -> McpStdioClient:
        if name not in self._clients:
            spec: LaunchSpec = launch_for(server, self._store)
            client = McpStdioClient(spec.argv, env=spec.env)
            try:
                await client.start()
            except BaseException:
                await client.close()
                raise
            self._clients[name] = client
        return self._clients[name]

    async def aclose(self) -> None:
        clients, self._clients = self._clients, {}
        for client in clients.values():
            with contextlib.suppress(Exception):
                await client.close()
