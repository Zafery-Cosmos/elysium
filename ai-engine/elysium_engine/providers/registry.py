"""Provider registry: DB config + keychain secrets -> live provider instances.

The registry merges the built-in catalog of known providers with the rows the
user configured (``providers`` table).  A provider is *configured* — and thus
routable — only once the user saved it via ``PUT /models/providers/{name}``
and, for remote providers, stored an API key in the keychain.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal

from elysium_engine.db.models import ProviderRecord
from elysium_engine.providers.anthropic import AnthropicProvider
from elysium_engine.providers.base import ModelInfo, ModelProvider
from elysium_engine.providers.openai_compat import OpenAICompatProvider
from elysium_engine.routing import ModelOption, Tier
from elysium_engine.secrets import SecretStore

ProviderKind = Literal["anthropic", "openai"]


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    """Static description of a known provider + its model catalog."""

    name: str
    kind: ProviderKind
    base_url: str
    is_local: bool
    default_model: str
    models: tuple[ModelInfo, ...]


# Costs are USD per Mtok; 0.0 for local models. Kept small on purpose: this is
# a routing catalog, not an exhaustive model list — users can point any
# OpenAI-compatible server at Elysium with a custom provider name.
KNOWN_PROVIDERS: dict[str, ProviderSpec] = {
    "anthropic": ProviderSpec(
        name="anthropic",
        kind="anthropic",
        base_url="https://api.anthropic.com",
        is_local=False,
        default_model="claude-sonnet-5",
        models=(
            ModelInfo("claude-opus-4-8", 1_000_000, 5.0, 25.0),
            ModelInfo("claude-sonnet-5", 1_000_000, 3.0, 15.0),
            ModelInfo("claude-haiku-4-5", 200_000, 1.0, 5.0),
        ),
    ),
    "openai": ProviderSpec(
        name="openai",
        kind="openai",
        base_url="https://api.openai.com/v1",
        is_local=False,
        default_model="gpt-4.1",
        models=(
            ModelInfo("gpt-4.1", 1_000_000, 2.0, 8.0),
            ModelInfo("gpt-4.1-mini", 1_000_000, 0.4, 1.6),
            ModelInfo("gpt-4.1-nano", 1_000_000, 0.1, 0.4),
        ),
    ),
    "ollama": ProviderSpec(
        name="ollama",
        kind="openai",
        base_url="http://localhost:11434/v1",
        is_local=True,
        default_model="llama3.1:8b",
        models=(
            ModelInfo("llama3.1:8b", 131_072, 0.0, 0.0),
            ModelInfo("qwen2.5-coder:14b", 131_072, 0.0, 0.0),
        ),
    ),
    "lmstudio": ProviderSpec(
        name="lmstudio",
        kind="openai",
        base_url="http://localhost:1234/v1",
        is_local=True,
        default_model="local-model",
        models=(ModelInfo("local-model", 32_768, 0.0, 0.0),),
    ),
    "openrouter": ProviderSpec(
        name="openrouter",
        kind="openai",
        base_url="https://openrouter.ai/api/v1",
        is_local=False,
        default_model="openrouter/auto",
        models=(ModelInfo("openrouter/auto", 200_000, 3.0, 15.0),),
    ),
    "deepseek": ProviderSpec(
        name="deepseek",
        kind="openai",
        base_url="https://api.deepseek.com/v1",
        is_local=False,
        default_model="deepseek-chat",
        models=(
            ModelInfo("deepseek-chat", 65_536, 0.27, 1.1),
            ModelInfo("deepseek-reasoner", 65_536, 0.55, 2.19),
        ),
    ),
    "mistral": ProviderSpec(
        name="mistral",
        kind="openai",
        base_url="https://api.mistral.ai/v1",
        is_local=False,
        default_model="mistral-large-latest",
        models=(
            ModelInfo("mistral-large-latest", 131_072, 2.0, 6.0),
            ModelInfo("mistral-small-latest", 32_768, 0.1, 0.3),
        ),
    ),
}

_MODEL_TIERS: dict[str, Tier] = {
    "claude-opus-4-8": "powerful",
    "claude-sonnet-5": "balanced",
    "claude-haiku-4-5": "fast",
    "gpt-4.1": "powerful",
    "gpt-4.1-mini": "balanced",
    "gpt-4.1-nano": "fast",
    "llama3.1:8b": "fast",
    "qwen2.5-coder:14b": "balanced",
    "deepseek-chat": "balanced",
    "deepseek-reasoner": "powerful",
    "mistral-large-latest": "powerful",
    "mistral-small-latest": "fast",
}


def model_tier(model_id: str) -> Tier:
    return _MODEL_TIERS.get(model_id, "balanced")


def spec_for(record: ProviderRecord) -> ProviderSpec:
    """Effective spec for a configured row: known defaults + user overrides."""
    known = KNOWN_PROVIDERS.get(record.name)
    if known is None:
        # Custom name -> generic OpenAI-compatible server.
        return ProviderSpec(
            name=record.name,
            kind="openai",
            base_url=record.base_url,
            is_local=record.is_local,
            default_model=record.default_model,
            models=(ModelInfo(record.default_model or "custom-model", 32_768, 0.0, 0.0),),
        )
    return replace(
        known,
        base_url=record.base_url or known.base_url,
        default_model=record.default_model or known.default_model,
        is_local=record.is_local,
    )


class ProviderRegistry:
    """Builds live providers from configured rows + keychain secrets."""

    def __init__(self, secret_store: SecretStore) -> None:
        self._secrets = secret_store

    def is_configured(self, spec: ProviderSpec) -> bool:
        return spec.is_local or self._secrets.get(spec.name) is not None

    def build(self, spec: ProviderSpec) -> ModelProvider | None:
        """Instantiate a provider, or None when it is missing its API key."""
        if not self.is_configured(spec):
            return None
        api_key = self._secrets.get(spec.name)
        if spec.kind == "anthropic":
            if api_key is None:
                return None
            return AnthropicProvider(
                api_key,
                name=spec.name,
                base_url=spec.base_url,
                default_model=spec.default_model,
                models=spec.models,
            )
        return OpenAICompatProvider(
            api_key,
            name=spec.name,
            base_url=spec.base_url,
            default_model=spec.default_model,
            models=spec.models,
        )

    def available_options(self, records: Sequence[ProviderRecord]) -> list[ModelOption]:
        """Routable (provider, model) options for :func:`routing.select_model`."""
        options: list[ModelOption] = []
        for record in records:
            spec = spec_for(record)
            if not self.is_configured(spec):
                continue
            for info in spec.models:
                options.append(
                    ModelOption(
                        provider=spec.name,
                        model=info.id,
                        tier=model_tier(info.id),
                        context_window=info.context_window,
                        input_cost=info.input_cost_per_mtok,
                        output_cost=info.output_cost_per_mtok,
                    )
                )
        return options

    def resolve(
        self, records: Sequence[ProviderRecord], provider_name: str
    ) -> ModelProvider | None:
        for record in records:
            if record.name == provider_name:
                return self.build(spec_for(record))
        return None
