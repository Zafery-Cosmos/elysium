"""Import of a personal sign-in token for Claude Code / Codex.

Instead of the browser flow, a user can paste a credential they produced
themselves, on their own machine:

* **Claude Code** — the long-lived token printed by ``claude setup-token``
  (a subscription token, ``sk-ant-oat01-...``).  It is kept in the OS keychain
  (never in the database or a file) and handed to the ``claude`` child process
  as ``CLAUDE_CODE_OAUTH_TOKEN``, and to that process only.
* **Codex** — the content of the ``auth.json`` file written by ``codex login``.
  It is installed into Elysium's *private* ``CODEX_HOME`` (the terminal's own
  ``~/.codex`` is never read or modified).

Elysium never reads the user's existing terminal credentials by itself: the
user pastes what they choose to share.  Tokens are personal — they belong to the
account holder and must not be shared or resold (provider terms apply).  The
token is verified against the real CLI before it is kept; a token that does not
work is removed again.  Nothing here ever logs or returns a token.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

CLAUDE_TOKEN_KEY = "claude-code:oauth-token"
MAX_PASTE_CHARS = 64 * 1024

_CLAUDE_TOKEN = re.compile(r"^sk-ant-[A-Za-z0-9_\-]{30,400}$")
_ENV_PREFIX = re.compile(r"^(?:export\s+|set\s+|\$env:)?CLAUDE_CODE_OAUTH_TOKEN\s*[=:]\s*", re.I)


class TokenImportError(ValueError):
    """The pasted text is not a usable credential (message is safe to show)."""


def parse_claude_token(raw: str) -> str:
    """Extract the token from what was pasted (bare token, or ``export VAR=...``)."""
    text = (raw or "").strip()
    if len(text) > MAX_PASTE_CHARS:
        raise TokenImportError("That text is far too long to be a token.")
    text = _ENV_PREFIX.sub("", text).strip().strip("'\"")
    if not _CLAUDE_TOKEN.match(text):
        raise TokenImportError(
            "That does not look like a Claude token. Run `claude setup-token` in a terminal and "
            "paste the token it prints (it starts with sk-ant-)."
        )
    return text


def parse_codex_auth(raw: str) -> dict[str, Any]:
    """Validate the content of a Codex ``auth.json`` and return it as a dict."""
    text = (raw or "").strip()
    if not text:
        raise TokenImportError("Paste the content of the auth.json file written by `codex login`.")
    if len(text) > MAX_PASTE_CHARS:
        raise TokenImportError("That text is too long to be an auth.json file.")
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise TokenImportError("That is not valid JSON. Paste the whole auth.json file.") from exc
    tokens = data.get("tokens") if isinstance(data, dict) else None
    if not isinstance(tokens, dict) or not all(
        isinstance(tokens.get(k), str) and tokens[k].strip() for k in ("access_token", "refresh_token")
    ):
        raise TokenImportError(
            "This auth.json has no ChatGPT sign-in tokens (tokens.access_token / refresh_token). "
            "Sign in with `codex login` using your ChatGPT account first."
        )
    return data


def codex_auth_path(cli_home: Path) -> Path:
    return cli_home / "codex" / "auth.json"


def install_codex_auth(cli_home: Path, data: dict[str, Any]) -> Path | None:
    """Write ``auth.json`` into Elysium's private Codex home; returns the backup path."""
    target = codex_auth_path(cli_home)
    target.parent.mkdir(parents=True, exist_ok=True)
    backup: Path | None = None
    if target.exists():
        backup = target.with_name("auth.json.bak")
        shutil.copy2(target, backup)
    # Create with owner-only permissions from the start (no readable window).
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    return backup


def restore_codex_auth(cli_home: Path, backup: Path | None) -> None:
    """Undo :func:`install_codex_auth` after a failed verification."""
    target = codex_auth_path(cli_home)
    if backup is not None and backup.exists():
        shutil.move(backup, target)
    else:
        target.unlink(missing_ok=True)


def discard_codex_backup(backup: Path | None) -> None:
    if backup is not None:
        backup.unlink(missing_ok=True)


# ---- hand the Claude token to the claude child process only -----------------

_lookup: Callable[[str], str | None] | None = None


def set_token_lookup(lookup: Callable[[str], str | None] | None) -> None:
    """Where to read the stored Claude token from (the secret store)."""
    global _lookup
    _lookup = lookup


def claude_token() -> str | None:
    if _lookup is None:
        return None
    try:
        return _lookup(CLAUDE_TOKEN_KEY)
    except Exception:  # a broken keychain must not break every CLI call
        return None


def env_for(argv0: str) -> dict[str, str]:
    """Extra environment for this executable (only ``claude`` gets its token)."""
    # Either separator: the same code must work for "C:\x\claude.cmd" and "/usr/bin/claude".
    name = argv0.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if name == "claude" or name.startswith("claude."):
        token = claude_token()
        if token:
            return {"CLAUDE_CODE_OAUTH_TOKEN": token}
    return {}
