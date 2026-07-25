"""Provider registry: DB config + keychain secrets -> live provider instances.

The registry merges the built-in catalog of known providers with the rows the
user configured (``providers`` table).  A provider is *configured* — and thus
routable — only once the user saved it via ``PUT /models/providers/{name}``
(or ``POST /models/providers`` for custom servers) and, for known remote
providers, stored an API key in the keychain.  Local providers (Ollama,
LM Studio) and custom OpenAI-compatible servers need no key.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal

import httpx

from elysium_engine.db.models import ProviderRecord
from elysium_engine.providers.anthropic import AnthropicProvider
from elysium_engine.providers.base import ModelInfo, ModelProvider
from elysium_engine.providers.openai_compat import OpenAICompatProvider
from elysium_engine.routing import ModelOption, Tier
from elysium_engine.secrets import SecretStore

ProviderKind = Literal["anthropic", "openai"]

# Live probes (local model discovery, connectivity tests) must never hang the
# UI: they get a short overall timeout and fail soft.
PROBE_TIMEOUT = httpx.Timeout(1.5)

# Context window reported for live-discovered local models: the OpenAI list
# endpoint carries no context metadata, so we use a conservative default.
LOCAL_DEFAULT_CONTEXT_WINDOW = 32_768


@dataclass(frozen=True, slots=True)
class PromptCacheConfig:
    """Prompt-caching knobs (from AppSettings.prompt_caching), Anthropic only."""

    enabled: bool = False
    ttl: str = "5m"
    min_prefix_tokens: int = 0


@dataclass(frozen=True, slots=True)
class ProviderCallConfig:
    """Provider call knobs (from AppSettings.ai), applied at build time.

    All ``None`` -> the provider keeps its built-in defaults, so an unconfigured
    engine behaves exactly as before. ``streaming`` is a default consumed by the
    agent runtime (the ``chat`` call path), not by the provider itself.
    """

    max_tokens: int | None = None
    timeout_s: float | None = None
    max_retries: int | None = None
    streaming: bool = True


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    """Static description of a known provider + its model catalog."""

    name: str
    kind: ProviderKind
    base_url: str
    is_local: bool
    default_model: str
    models: tuple[ModelInfo, ...]


# Curated catalog spanning ~2023 -> 2026 per provider. Costs are USD per Mtok
# (approximate where providers only publish ranges); 0.0 for local models.
# Users can point any other OpenAI-compatible server at Elysium by registering
# a custom provider (POST /models/providers).
KNOWN_PROVIDERS: dict[str, ProviderSpec] = {
    "anthropic": ProviderSpec(
        name="anthropic",
        kind="anthropic",
        base_url="https://api.anthropic.com",
        is_local=False,
        default_model="claude-sonnet-5",
        models=(
            ModelInfo("claude-fable-5", 1_000_000, 10.0, 50.0, "Claude Fable 5", "2026-06"),
            ModelInfo("claude-opus-4-8", 1_000_000, 5.0, 25.0, "Claude Opus 4.8", "2026-05"),
            ModelInfo("claude-opus-4-7", 1_000_000, 5.0, 25.0, "Claude Opus 4.7", "2026-03"),
            ModelInfo("claude-opus-4-6", 1_000_000, 5.0, 25.0, "Claude Opus 4.6", "2026-01"),
            ModelInfo("claude-opus-4-5", 200_000, 5.0, 25.0, "Claude Opus 4.5", "2025-11"),
            ModelInfo("claude-sonnet-5", 1_000_000, 3.0, 15.0, "Claude Sonnet 5", "2026-04"),
            ModelInfo("claude-sonnet-4-6", 1_000_000, 3.0, 15.0, "Claude Sonnet 4.6", "2025-12"),
            ModelInfo("claude-sonnet-4-5", 200_000, 3.0, 15.0, "Claude Sonnet 4.5", "2025-09"),
            ModelInfo("claude-haiku-4-5", 200_000, 1.0, 5.0, "Claude Haiku 4.5", "2025-10"),
            ModelInfo(
                "claude-3-haiku-20240307", 200_000, 0.25, 1.25, "Claude 3 Haiku", "2024-03"
            ),
        ),
    ),
    "openai": ProviderSpec(
        name="openai",
        kind="openai",
        base_url="https://api.openai.com/v1",
        is_local=False,
        default_model="gpt-5",
        models=(
            ModelInfo("gpt-5", 400_000, 1.25, 10.0, "GPT-5", "2025-08"),
            ModelInfo("gpt-5-mini", 400_000, 0.25, 2.0, "GPT-5 Mini", "2025-08"),
            ModelInfo("gpt-5-nano", 400_000, 0.05, 0.4, "GPT-5 Nano", "2025-08"),
            ModelInfo("gpt-4.1", 1_000_000, 2.0, 8.0, "GPT-4.1", "2025-04"),
            ModelInfo("gpt-4.1-mini", 1_000_000, 0.4, 1.6, "GPT-4.1 Mini", "2025-04"),
            ModelInfo("gpt-4.1-nano", 1_000_000, 0.1, 0.4, "GPT-4.1 Nano", "2025-04"),
            ModelInfo("gpt-4o", 128_000, 2.5, 10.0, "GPT-4o", "2024-05"),
            ModelInfo("gpt-4o-mini", 128_000, 0.15, 0.6, "GPT-4o Mini", "2024-07"),
            ModelInfo("o3", 200_000, 2.0, 8.0, "o3", "2025-04"),
            ModelInfo("gpt-3.5-turbo", 16_384, 0.5, 1.5, "GPT-3.5 Turbo", "2023-03"),
        ),
    ),
    "google": ProviderSpec(
        name="google",
        kind="openai",  # Gemini exposes an OpenAI-compatible surface (ADR-004)
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        is_local=False,
        default_model="gemini-2.5-flash",
        models=(
            ModelInfo("gemini-2.5-pro", 1_000_000, 1.25, 10.0, "Gemini 2.5 Pro", "2025-03"),
            ModelInfo("gemini-2.5-flash", 1_000_000, 0.3, 2.5, "Gemini 2.5 Flash", "2025-05"),
            ModelInfo("gemini-2.0-flash", 1_000_000, 0.1, 0.4, "Gemini 2.0 Flash", "2025-02"),
            ModelInfo("gemini-1.5-pro", 2_000_000, 1.25, 5.0, "Gemini 1.5 Pro", "2024-02"),
        ),
    ),
    "ollama": ProviderSpec(
        name="ollama",
        kind="openai",
        base_url="http://localhost:11434/v1",
        is_local=True,
        default_model="llama3.1:8b",
        # Static fallback only: GET /models live-probes the server for the
        # actually installed models and uses these when it is unreachable.
        models=(
            ModelInfo("llama3.1:8b", 131_072, 0.0, 0.0, "Llama 3.1 8B"),
            ModelInfo("qwen2.5-coder:14b", 131_072, 0.0, 0.0, "Qwen2.5 Coder 14B"),
        ),
    ),
    "lmstudio": ProviderSpec(
        name="lmstudio",
        kind="openai",
        base_url="http://localhost:1234/v1",
        is_local=True,
        default_model="local-model",
        models=(ModelInfo("local-model", 32_768, 0.0, 0.0, "Modèle local"),),
    ),
    "openrouter": ProviderSpec(
        name="openrouter",
        kind="openai",
        base_url="https://openrouter.ai/api/v1",
        is_local=False,
        default_model="openrouter/auto",
        models=(ModelInfo("openrouter/auto", 200_000, 3.0, 15.0, "OpenRouter Auto"),),
    ),
    "deepseek": ProviderSpec(
        name="deepseek",
        kind="openai",
        base_url="https://api.deepseek.com/v1",
        is_local=False,
        default_model="deepseek-chat",
        models=(
            ModelInfo("deepseek-chat", 65_536, 0.27, 1.1, "DeepSeek V3", "2024-12"),
            ModelInfo("deepseek-reasoner", 65_536, 0.55, 2.19, "DeepSeek R1", "2025-01"),
        ),
    ),
    "mistral": ProviderSpec(
        name="mistral",
        kind="openai",
        base_url="https://api.mistral.ai/v1",
        is_local=False,
        default_model="mistral-large-latest",
        models=(
            ModelInfo("mistral-large-latest", 131_072, 2.0, 6.0, "Mistral Large", "2024-02"),
            ModelInfo("mistral-medium-latest", 131_072, 0.4, 2.0, "Mistral Medium", "2025-05"),
            ModelInfo("mistral-small-latest", 131_072, 0.1, 0.3, "Mistral Small", "2024-09"),
            ModelInfo("codestral-latest", 256_000, 0.3, 0.9, "Codestral", "2024-05"),
        ),
    ),
}

_MODEL_TIERS: dict[str, Tier] = {
    # anthropic
    "claude-fable-5": "powerful",
    "claude-opus-4-8": "powerful",
    "claude-opus-4-7": "powerful",
    "claude-opus-4-6": "powerful",
    "claude-opus-4-5": "powerful",
    "claude-sonnet-5": "balanced",
    "claude-sonnet-4-6": "balanced",
    "claude-sonnet-4-5": "balanced",
    "claude-haiku-4-5": "fast",
    "claude-3-haiku-20240307": "fast",
    # openai
    "gpt-5": "powerful",
    "gpt-5-mini": "balanced",
    "gpt-5-nano": "fast",
    "gpt-4.1": "powerful",
    "gpt-4.1-mini": "balanced",
    "gpt-4.1-nano": "fast",
    "gpt-4o": "balanced",
    "gpt-4o-mini": "fast",
    "o3": "powerful",
    "gpt-3.5-turbo": "fast",
    # google
    "gemini-2.5-pro": "powerful",
    "gemini-2.5-flash": "balanced",
    "gemini-2.0-flash": "fast",
    "gemini-1.5-pro": "balanced",
    # local fallbacks
    "llama3.1:8b": "fast",
    "qwen2.5-coder:14b": "balanced",
    # deepseek
    "deepseek-chat": "balanced",
    "deepseek-reasoner": "powerful",
    # mistral
    "mistral-large-latest": "powerful",
    "mistral-medium-latest": "balanced",
    "mistral-small-latest": "fast",
    "codestral-latest": "balanced",
}


def model_tier(model_id: str) -> Tier:
    return _MODEL_TIERS.get(model_id, "balanced")


def is_known_provider(name: str) -> bool:
    return name in KNOWN_PROVIDERS


def spec_for(record: ProviderRecord) -> ProviderSpec:
    """Effective spec for a configured row: known defaults + user overrides."""
    known = KNOWN_PROVIDERS.get(record.name)
    if known is None:
        # Custom name -> generic OpenAI-compatible server.
        default_model = record.default_model or "custom-model"
        return ProviderSpec(
            name=record.name,
            kind="openai",
            base_url=record.base_url,
            is_local=record.is_local,
            default_model=record.default_model,
            models=(
                ModelInfo(default_model, 32_768, 0.0, 0.0, display_name=default_model),
            ),
        )
    return replace(
        known,
        base_url=record.base_url or known.base_url,
        default_model=record.default_model or known.default_model,
        is_local=record.is_local,
    )


def _models_list_url(spec: ProviderSpec) -> str:
    base = spec.base_url.rstrip("/")
    if spec.kind == "anthropic":
        return f"{base}/v1/models"
    return f"{base}/models"


@contextlib.asynccontextmanager
async def _probe_client_or_default(
    injected: httpx.AsyncClient | None,
) -> AsyncIterator[httpx.AsyncClient]:
    """Use the injected client (tests use a MockTransport) or a short-timeout one."""
    if injected is not None:
        yield injected
    else:
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT) as client:
            yield client


class ProviderRegistry:
    """Builds live providers from configured rows + keychain secrets.

    ``probe_client`` and ``chat_client`` exist for dependency injection: tests
    hand in ``httpx.AsyncClient(transport=httpx.MockTransport(...))`` so no
    probe or chat call ever leaves the process.
    """

    def __init__(
        self,
        secret_store: SecretStore,
        probe_client: httpx.AsyncClient | None = None,
        chat_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._secrets = secret_store
        self.probe_client = probe_client
        self.chat_client = chat_client

    def is_configured(self, spec: ProviderSpec) -> bool:
        # Local servers and custom OpenAI-compatible servers may be keyless;
        # known remote providers require an API key in the keychain.
        if spec.is_local or not is_known_provider(spec.name):
            return True
        return self._secrets.get(spec.name) is not None

    def build(
        self,
        spec: ProviderSpec,
        cache: "PromptCacheConfig | None" = None,
        call: "ProviderCallConfig | None" = None,
    ) -> ModelProvider | None:
        """Instantiate a provider, or None when it is missing its API key.

        ``cache`` (Anthropic only) turns on system-prompt prefix caching;
        ``call`` carries the AppSettings.ai request knobs (max tokens, timeout,
        retries) applied to the outbound HTTP call.
        """
        if not self.is_configured(spec):
            return None
        api_key = self._secrets.get(spec.name)
        call = call or ProviderCallConfig()
        if spec.kind == "anthropic":
            if api_key is None:
                return None
            cache = cache or PromptCacheConfig()
            return AnthropicProvider(
                api_key,
                name=spec.name,
                base_url=spec.base_url,
                default_model=spec.default_model,
                models=spec.models,
                client=self.chat_client,
                cache_system_prompt=cache.enabled,
                cache_ttl=cache.ttl,
                cache_min_tokens=cache.min_prefix_tokens,
                max_tokens=call.max_tokens,
                timeout_s=call.timeout_s,
                max_retries=call.max_retries,
            )
        return OpenAICompatProvider(
            api_key,
            name=spec.name,
            base_url=spec.base_url,
            default_model=spec.default_model,
            models=spec.models,
            client=self.chat_client,
            max_tokens=call.max_tokens,
            timeout_s=call.timeout_s,
            max_retries=call.max_retries,
        )

    def _probe_headers(self, spec: ProviderSpec) -> dict[str, str]:
        api_key = self._secrets.get(spec.name)
        if spec.kind == "anthropic":
            return {"x-api-key": api_key or "", "anthropic-version": "2023-06-01"}
        return {"authorization": f"Bearer {api_key}"} if api_key else {}

    async def probe(self, spec: ProviderSpec) -> tuple[bool, str | None]:
        """Connectivity test against the models-list endpoint -> (reachable, detail)."""
        url = _models_list_url(spec)
        try:
            async with _probe_client_or_default(self.probe_client) as client:
                response = await client.get(url, headers=self._probe_headers(spec))
        except httpx.HTTPError as exc:
            return False, f"{type(exc).__name__}: {exc}"
        if response.status_code == 200:
            return True, None
        return False, f"HTTP {response.status_code}: {response.text[:200]}"

    async def discover_local_models(
        self, spec: ProviderSpec
    ) -> tuple[tuple[ModelInfo, ...], bool]:
        """Live-list the models actually installed on a local server.

        Returns ``(models, reachable)``.  On any failure the static fallback
        catalog is returned with ``reachable=False`` so the UI stays useful.
        """
        url = _models_list_url(spec)
        try:
            async with _probe_client_or_default(self.probe_client) as client:
                response = await client.get(url, headers=self._probe_headers(spec))
            if response.status_code != 200:
                return spec.models, False
            body: Any = response.json()
            entries = body.get("data") if isinstance(body, dict) else None
            if not isinstance(entries, list):
                return spec.models, False
        except (httpx.HTTPError, ValueError):
            return spec.models, False

        discovered = tuple(
            ModelInfo(
                id=str(entry["id"]),
                context_window=LOCAL_DEFAULT_CONTEXT_WINDOW,
                input_cost_per_mtok=0.0,
                output_cost_per_mtok=0.0,
                display_name=str(entry["id"]),
            )
            for entry in entries
            if isinstance(entry, dict) and entry.get("id")
        )
        return discovered, True

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
        self,
        records: Sequence[ProviderRecord],
        provider_name: str,
        cache: "PromptCacheConfig | None" = None,
        call: "ProviderCallConfig | None" = None,
    ) -> ModelProvider | None:
        for record in records:
            if record.name == provider_name:
                return self.build(spec_for(record), cache, call)
        return None
