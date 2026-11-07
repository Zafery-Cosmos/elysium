"""Interactive sign-in sessions for CLI-backed providers (Claude Code / Codex).

The vendor CLI owns the whole OAuth exchange.  A session just runs its login
command, surfaces what it prints (the sign-in URL, a device code, the
"paste code" prompt) and relays what the user pastes back.  Elysium never
sees, stores or forwards an OAuth token.

Supported ways to finish a sign-in:

* **Browser** (default): the CLI opens the system browser; nothing to paste.
* **Paste a code**: Claude shows a code on ``platform.claude.com`` and waits at
  ``Paste code here if prompted >``.  Works from any machine, so the URL can be
  opened elsewhere (another computer, another person's browser).
* **Paste a redirect address**: the CLI's loopback callback
  (``http://127.0.0.1:<port>/...?code=...&state=...``) fails when the browser
  is not on the same machine; pasting that address here replays it locally.
* **Device code** (Codex ``--device-auth``): open a link, type a one-time code.
"""

from __future__ import annotations

import codecs
import contextlib
import re
import subprocess
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from urllib.parse import parse_qs, urlparse

import httpx

from elysium_engine.providers.base import ProviderError
from elysium_engine.providers.cli_common import _NO_WINDOW, _clean_env, sandbox_dir

LoginMode = Literal["browser", "device"]

SESSION_TTL_S = 15 * 60  # codes/links expire; never keep a login process forever

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_URL = re.compile(r"https?://[^\s\x1b<>\"']+")
_DEVICE_CODE = re.compile(r"\b[A-Z0-9]{4}-[A-Z0-9]{4,6}\b")
_LOOPBACK = {"127.0.0.1", "localhost", "::1", "[::1]"}


def _strip(text: str) -> str:
    return _ANSI.sub("", text).replace("\r", "")


def _first_external_url(text: str) -> str | None:
    """First URL that is not the CLI's own loopback callback server."""
    for match in _URL.finditer(text):
        url = match.group(0).rstrip(".,;)")
        if urlparse(url).hostname not in _LOOPBACK:
            return url
    return None


@dataclass(frozen=True, slots=True)
class PastedInput:
    """What a pasted string means: send ``value`` to the CLI, or replay a URL."""

    kind: Literal["stdin", "forward"]
    value: str


def interpret_pasted(raw: str, expected_state: str | None = None) -> PastedInput:
    """Classify what the user pasted.

    * a bare code (``abc`` or ``abc#state``)        -> written to the CLI's stdin
    * a redirect address on the vendor's own site   -> its ``code#state`` to stdin
    * a loopback address (``127.0.0.1``/``localhost``) -> replayed as a local GET

    Loopback replays must carry the ``code`` and, when the session's ``state``
    is known, the *same* ``state`` — so only a callback that belongs to this
    very sign-in can be replayed, never an arbitrary URL.
    """
    text = raw.strip()
    if not text:
        raise ValueError("Nothing to send: paste the code or the redirect address.")
    if not re.match(r"https?://", text, re.IGNORECASE):
        if "\n" in text or len(text) > 2048:
            raise ValueError("That does not look like a sign-in code.")
        return PastedInput("stdin", text)

    parsed = urlparse(text)
    query = parse_qs(parsed.query)
    code = (query.get("code") or [""])[0]
    state = (query.get("state") or [""])[0]
    if not code:
        raise ValueError("This address has no sign-in code in it.")
    if parsed.hostname in _LOOPBACK:
        if expected_state and state != expected_state:
            raise ValueError("This address belongs to a different sign-in attempt.")
        return PastedInput("forward", text)
    return PastedInput("stdin", f"{code}#{state}" if state else code)


class LoginSession:
    """One running login command for one provider."""

    def __init__(self, provider: str, argv: Sequence[str], *, device: bool = False) -> None:
        self.provider = provider
        self.device = device
        self.started_at = time.monotonic()
        self._lock = threading.Lock()
        self._text = ""
        self._cancelled = False
        try:
            self._proc = subprocess.Popen(  # noqa: S603 - argv list, no shell
                list(argv),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=str(sandbox_dir()),
                env=_clean_env(),
                creationflags=_NO_WINDOW,
            )
        except OSError as exc:
            raise ProviderError(f"{provider}: cannot start '{argv[0]}': {exc}") from exc
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        stdout = self._proc.stdout
        assert stdout is not None
        while True:
            chunk = stdout.read1(512)  # type: ignore[attr-defined]
            if not chunk:
                break
            piece = decoder.decode(chunk)
            with self._lock:
                self._text += piece

    # -- observable state ---------------------------------------------------

    def _output(self) -> str:
        with self._lock:
            return _strip(self._text)

    @property
    def auth_url(self) -> str | None:
        return _first_external_url(self._output())

    @property
    def auth_state(self) -> str | None:
        url = self.auth_url
        if url is None:
            return None
        return (parse_qs(urlparse(url).query).get("state") or [None])[0]

    @property
    def device_code(self) -> str | None:
        if not self.device:
            return None
        text = self._output()
        url_match = _URL.search(text)
        tail = text[url_match.end() :] if url_match else text
        match = _DEVICE_CODE.search(tail)
        return match.group(0) if match else None

    @property
    def accepts_input(self) -> bool:
        """True while pasting a code / redirect address can still finish the sign-in."""
        return not self.device and not self.finished and self.auth_url is not None

    @property
    def finished(self) -> bool:
        return self._proc.poll() is not None

    @property
    def succeeded(self) -> bool:
        return self._proc.poll() == 0

    @property
    def error(self) -> str | None:
        if not self.finished or self.succeeded:
            return None
        if self._cancelled:
            return "Sign-in cancelled."
        lines = [ln.strip() for ln in self._output().splitlines() if ln.strip()]
        return lines[-1][:300] if lines else "The sign-in did not complete."

    @property
    def expired(self) -> bool:
        return time.monotonic() - self.started_at > SESSION_TTL_S

    # -- actions --------------------------------------------------------------

    def submit(self, raw: str) -> None:
        """Relay a pasted code / redirect address (see :func:`interpret_pasted`)."""
        if self.finished:
            raise ValueError("This sign-in is already over. Start a new one.")
        pasted = interpret_pasted(raw, self.auth_state)
        if pasted.kind == "forward":
            # Replay the loopback callback to the CLI's own local server.
            try:
                httpx.get(pasted.value, timeout=10.0, follow_redirects=False)
            except httpx.HTTPError as exc:
                raise ValueError(
                    "Could not reach the sign-in listener on this computer. "
                    "Start the sign-in again and paste the new address."
                ) from exc
            return
        stdin = self._proc.stdin
        if stdin is None:
            raise ValueError("This sign-in does not accept a pasted code.")
        try:
            stdin.write((pasted.value + "\n").encode("utf-8"))
            stdin.flush()
        except OSError as exc:
            raise ValueError("The sign-in process is no longer listening.") from exc

    def cancel(self) -> None:
        self._cancelled = True
        if self._proc.poll() is None:
            with contextlib.suppress(OSError):
                self._proc.kill()
        with contextlib.suppress(OSError):
            if self._proc.stdin is not None:
                self._proc.stdin.close()


class CliLoginManager:
    """At most one live login session per provider."""

    def __init__(self) -> None:
        self._sessions: dict[str, LoginSession] = {}

    def start(
        self, provider: str, argv: Sequence[str], *, device: bool = False
    ) -> LoginSession:
        self.cancel(provider)
        session = LoginSession(provider, argv, device=device)
        self._sessions[provider] = session
        return session

    def get(self, provider: str) -> LoginSession | None:
        session = self._sessions.get(provider)
        if session is not None and session.expired and not session.finished:
            session.cancel()
        return session

    def cancel(self, provider: str) -> None:
        session = self._sessions.pop(provider, None)
        if session is not None:
            session.cancel()

    def shutdown(self) -> None:
        for name in list(self._sessions):
            self.cancel(name)
