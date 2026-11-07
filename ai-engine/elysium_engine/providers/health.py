"""Provider health: can this provider *really* answer right now?

An installed binary or a saved key is not proof of anything.  States:

``not_installed``      CLI missing on this computer
``not_authenticated``  CLI installed but not signed in / no API key saved
``authenticated``      credentials exist, no call attempted recently
``available``          a recent call succeeded
``unavailable``        recent network / server failure or timeout
``auth_error``         the provider rejected the credentials
``quota_exhausted``    plan window used up or API quota / credit exhausted
``unknown``            we simply do not know (never treated as available)

Routing only uses providers in a *usable* state; skipping or replacing one is
reported to the user, never silent.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from elysium_engine.providers import quota

if TYPE_CHECKING:
    from elysium_engine.providers.registry import ProviderRegistry

STATES = (
    "not_installed",
    "not_authenticated",
    "authenticated",
    "available",
    "unavailable",
    "auth_error",
    "quota_exhausted",
    "unknown",
)
BLOCKING = frozenset({"not_installed", "not_authenticated", "auth_error", "quota_exhausted"})

ERROR_TTL_S = 10 * 60
OK_TTL_S = 30 * 60
# How long a call outcome keeps describing the provider (a rate limit clears
# quickly; a rejected key does not fix itself).
_TTL = {"available": OK_TTL_S, "quota_exhausted": 120.0, "unavailable": 60.0, "auth_error": ERROR_TTL_S}
CLI_CHECK_TTL_S = 60
CLI_CHECK_TIMEOUT_S = 15.0
CLI_NAMES = {"claude-code": "claude", "codex": "codex"}

_AUTH = re.compile(
    r"(?i)(\b401\b|\b403\b|unauthori[sz]ed|invalid[ _-]?(api[ _-]?)?key|authentication|not (signed|logged) in|"
    r"incorrect api key|permission_denied|forbidden)"
)
_QUOTA = re.compile(
    r"(?i)(\b429\b|rate.?limit|quota|insufficient[_ ]|credit|usage limit|billing|too many requests|limit reached)"
)


def classify_error(message: str) -> str:
    """Map a provider failure message to a health state."""
    if _AUTH.search(message):
        return "auth_error"
    if _QUOTA.search(message):
        return "quota_exhausted"
    return "unavailable"


@dataclass(frozen=True, slots=True)
class Health:
    state: str
    detail: str | None = None
    checked_at: float | None = None

    @property
    def usable(self) -> bool:
        return self.state not in BLOCKING


class HealthLedger:
    def __init__(self) -> None:
        self._calls: dict[str, tuple[str, str | None, float]] = {}  # name -> (state, detail, at)
        self._cli: dict[str, tuple[bool, bool, str | None, float]] = {}  # installed, signed_in, detail, at

    def note_ok(self, provider: str) -> None:
        self._calls[provider] = ("available", None, time.time())

    def note_error(self, provider: str, message: str) -> None:
        self._calls[provider] = (classify_error(message), message[:300], time.time())

    def set_cli(self, provider: str, installed: bool, signed_in: bool, detail: str | None) -> None:
        self._cli[provider] = (installed, signed_in, detail, time.time())

    def cli_checked_recently(self, provider: str, now: float | None = None) -> bool:
        entry = self._cli.get(provider)
        return entry is not None and (now or time.time()) - entry[3] < CLI_CHECK_TTL_S

    def health(self, provider: str, *, kind: str, configured: bool, now: float | None = None) -> Health:
        """Current health of one provider. ``kind`` is the registry kind (``cli`` / other)."""
        now = time.time() if now is None else now
        if kind == "cli":
            if not configured:  # for a CLI, "configured" means "installed"
                return Health("not_installed", "The command-line tool is not installed.", now)
            entry = self._cli.get(provider)
            if entry is not None and not entry[1]:
                return Health("not_authenticated", entry[2] or "Not signed in.", entry[3])
            if quota.is_exhausted(provider, now):
                return Health("quota_exhausted", "Plan usage window exhausted.", now)
            base = "authenticated" if entry is not None else "unknown"
        else:
            if not configured:
                return Health("not_authenticated", "No API key saved.", now)
            base = "authenticated"
        call = self._calls.get(provider)
        if call is not None:
            state, detail, at = call
            if now - at < _TTL.get(state, ERROR_TTL_S):
                return Health(state, detail, at)
        return Health(base, None, None)

    def reset(self) -> None:
        self._calls.clear()
        self._cli.clear()


LEDGER = HealthLedger()


async def refresh_cli(registry: ProviderRegistry, names: tuple[str, ...] = tuple(CLI_NAMES)) -> None:
    """Check sign-in state of the CLI providers (cached 60 s, 15 s timeout each)."""
    from elysium_engine.providers.registry import KNOWN_PROVIDERS

    for name in names:
        if not registry.is_configured(KNOWN_PROVIDERS[name]):
            LEDGER.set_cli(name, False, False, "not installed")
            continue
        if LEDGER.cli_checked_recently(name):
            continue
        try:
            signed_in, detail, _ = await asyncio.wait_for(
                registry.cli_state(name), timeout=CLI_CHECK_TIMEOUT_S
            )
        except (TimeoutError, asyncio.TimeoutError):
            LEDGER._calls[name] = ("unavailable", "Sign-in check timed out.", time.time())  # noqa: SLF001
            continue
        LEDGER.set_cli(name, True, bool(signed_in), detail)
