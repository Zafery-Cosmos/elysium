"""Settings that must really change engine behaviour (no cosmetic toggles)."""

from __future__ import annotations

import pytest

from elysium_engine.agents.project_manager import pm_system_prompt
from elysium_engine.api.routers.conversations import _resolve_pm_model
from elysium_engine.app_settings import AiSettings
from elysium_engine.db.models import ProviderRecord
from elysium_engine.providers.base import ModelInfo, ModelProvider
from elysium_engine.providers.redaction import RedactingProvider, redact_secrets
from elysium_engine.providers.registry import (
    KNOWN_PROVIDERS,
    ProviderCallConfig,
    ProviderRegistry,
)
from tests.conftest import collect


class _Secrets:
    def get(self, name: str) -> str | None:
        return "key"

    def set(self, name: str, value: str) -> None: ...


def _record(name: str, *, is_local: bool = False) -> ProviderRecord:
    return ProviderRecord(name=name, base_url="", default_model="", is_local=is_local)


# --------------------------------------------------------------- redaction


@pytest.mark.parametrize(
    "secret",
    [
        "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123",
        "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        "AKIAABCDEFGHIJKLMNOP",
        "-----BEGIN RSA PRIVATE KEY-----\nMIIB\n-----END RSA PRIVATE KEY-----",
    ],
)
def test_known_secret_formats_are_redacted(secret: str) -> None:
    out = redact_secrets(f"use this: {secret} please")
    assert secret not in out and "[REDACTED]" in out


def test_assignments_keep_the_key_and_hide_the_value() -> None:
    out = redact_secrets('password = "hunter2hunter2"\nAPI_KEY: abcdef123456')
    assert "hunter2" not in out and "abcdef123456" not in out
    assert "password" in out and "API_KEY" in out


def test_normal_text_is_untouched() -> None:
    text = "Build me a CRM with a token-based login for 10 users."
    assert redact_secrets(text) == text


class _Spy(ModelProvider):
    name = "spy"
    base_url = "x"
    default_model = "m"

    def __init__(self) -> None:
        self.seen: list[object] = []

    def models(self) -> list[ModelInfo]:
        return []

    async def chat(self, messages, tools=None, stream=False, model=None, effort=None):  # type: ignore[no-untyped-def]
        self.seen = list(messages)
        yield {"type": "done", "stop_reason": None, "input_tokens": 1, "output_tokens": 1}


async def test_redacting_provider_scrubs_before_sending() -> None:
    spy = _Spy()
    provider = RedactingProvider(spy)
    await collect(
        provider.chat([{"role": "user", "content": "key ghp_abcdefghijklmnopqrstuvwxyz0123456789"}])
    )
    assert "ghp_" not in spy.seen[0]["content"]  # type: ignore[index]
    assert provider.name == "spy"


def test_registry_wraps_when_redaction_is_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("elysium_engine.providers.registry.find_binary", lambda _n: "claude")
    registry = ProviderRegistry(_Secrets())  # type: ignore[arg-type]
    spec = KNOWN_PROVIDERS["claude-code"]
    assert not isinstance(registry.build(spec), RedactingProvider)
    assert isinstance(
        registry.build(spec, call=ProviderCallConfig(redact_secrets=True)), RedactingProvider
    )


# ---------------------------------------------------------------- local only


def test_local_only_blocks_cloud_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("elysium_engine.providers.registry.find_binary", lambda _n: "claude")
    registry = ProviderRegistry(_Secrets())  # type: ignore[arg-type]
    call = ProviderCallConfig(local_only=True)
    assert registry.build(KNOWN_PROVIDERS["claude-code"], call=call) is None
    assert registry.build(KNOWN_PROVIDERS["anthropic"], call=call) is None
    assert registry.build(KNOWN_PROVIDERS["ollama"], call=call) is not None


def test_local_only_hides_cloud_models_from_routing() -> None:
    registry = ProviderRegistry(_Secrets())  # type: ignore[arg-type]
    records = [_record("openai"), _record("ollama", is_local=True)]
    providers = {o.provider for o in registry.available_options(records, local_only=True)}
    assert providers == {"ollama"}


# ------------------------------------------------------------ default model


def _registry_and_records():  # type: ignore[no-untyped-def]
    return ProviderRegistry(_Secrets()), [_record("anthropic"), _record("openai")]  # type: ignore[arg-type]


def test_explicit_default_model_wins() -> None:
    registry, records = _registry_and_records()
    ai = AiSettings(default_provider="openai", default_model="gpt-5.5")
    provider, model = _resolve_pm_model(registry, records, "hi", None, None, ai)
    assert provider is not None and provider.name == "openai" and model == "gpt-5.5"


def test_default_provider_alone_restricts_routing() -> None:
    registry, records = _registry_and_records()
    ai = AiSettings(default_provider="openai")
    provider, model = _resolve_pm_model(registry, records, "hi", None, None, ai)
    assert provider is not None and provider.name == "openai"
    assert model in {m.id for m in KNOWN_PROVIDERS["openai"].models}


def test_auto_routing_off_uses_first_configured_model() -> None:
    registry, records = _registry_and_records()
    ai = AiSettings(auto_routing=False)
    provider, model = _resolve_pm_model(registry, records, "hi", None, None, ai)
    assert provider is not None and provider.name == "anthropic"
    assert model == KNOWN_PROVIDERS["anthropic"].models[0].id


def test_unknown_default_falls_back_to_routing() -> None:
    registry, records = _registry_and_records()
    ai = AiSettings(default_provider="openai", default_model="does-not-exist")
    provider, _ = _resolve_pm_model(registry, records, "hi", None, None, ai)
    assert provider is not None and provider.name == "openai"


# ------------------------------------------------------------ response language


def test_response_language_is_added_to_the_prompt() -> None:
    assert "always answer in Spanish" in pm_system_prompt(response_language="es")
    assert "RESPONSE LANGUAGE" not in pm_system_prompt(response_language="auto")
