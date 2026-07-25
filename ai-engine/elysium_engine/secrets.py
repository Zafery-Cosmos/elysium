"""Provider API-key storage.

Keys live in the OS keychain via ``keyring`` under the service name
``"elysium"`` — never in the database or config files (ARCHITECTURE.md §7).

Fallback: on headless machines and in CI there is often no keychain backend
(``keyring`` then exposes its ``fail.Keyring``).  In that case we degrade to a
process-local **in-memory** store and log a warning: keys still never touch
disk, but they are lost when the engine stops and must be re-entered.
"""

from __future__ import annotations

import logging
from typing import Protocol

import keyring
import keyring.backends.fail
import keyring.errors

SERVICE_NAME = "elysium"

log = logging.getLogger(__name__)


class SecretStore(Protocol):
    def get(self, name: str) -> str | None: ...

    def set(self, name: str, value: str) -> None: ...

    def delete(self, name: str) -> None: ...


class KeyringSecretStore:
    """OS-keychain-backed store (the normal desktop path)."""

    def get(self, name: str) -> str | None:
        return keyring.get_password(SERVICE_NAME, name)

    def set(self, name: str, value: str) -> None:
        keyring.set_password(SERVICE_NAME, name, value)

    def delete(self, name: str) -> None:
        try:
            keyring.delete_password(SERVICE_NAME, name)
        except keyring.errors.PasswordDeleteError:
            pass  # deleting an absent key is a no-op, not an error


class InMemorySecretStore:
    """Volatile fallback when no keychain backend is usable (headless/CI)."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        return self._data.get(name)

    def set(self, name: str, value: str) -> None:
        self._data[name] = value

    def delete(self, name: str) -> None:
        self._data.pop(name, None)


def build_secret_store() -> SecretStore:
    """Return the keychain store, or the in-memory fallback with a warning."""
    try:
        backend = keyring.get_keyring()
        if isinstance(backend, keyring.backends.fail.Keyring):
            raise keyring.errors.NoKeyringError("no keychain backend available")
        # Some backends only fail at call time; probe before committing to it.
        keyring.get_password(SERVICE_NAME, "__elysium_probe__")
        return KeyringSecretStore()
    except keyring.errors.KeyringError as exc:
        log.warning(
            "No usable OS keychain backend (%s). Falling back to an in-memory "
            "secret store: provider API keys will NOT persist across restarts.",
            exc,
        )
        return InMemorySecretStore()
