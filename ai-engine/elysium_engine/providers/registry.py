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
from typing import TYPE_CHECKING, Any, Literal

import httpx

from elysium_engine.db.models import ProviderRecord
from elysium_engine.providers import claude_code, codex_cli
from elysium_engine.providers.anthropic import AnthropicProvider
from elysium_engine.providers.base import ModelInfo, ModelProvider, ProviderError
from elysium_engine.providers.claude_code import ClaudeCodeProvider
from elysium_engine.providers.cli_common import find_binary
from elysium_engine.providers.cli_token import CLAUDE_TOKEN_KEY
from elysium_engine.providers.codex_cli import CodexProvider
from elysium_engine.providers.openai_compat import OpenAICompatProvider
from elysium_engine.providers.redaction import RedactingProvider
from elysium_engine.routing import ModelOption, Tier
from elysium_engine.secrets import SecretStore

if TYPE_CHECKING:
    from elysium_engine.providers.health import Health

# "cli" = drives the user's own vendor CLI (Claude Code / Codex) signed in with
# their personal account: no API key, nothing stored in the keychain.
ProviderKind = Literal["anthropic", "openai", "cli"]

# Binary name per CLI-backed provider.
CLI_BINARIES: dict[str, str] = {"claude-code": "claude", "codex": "codex"}

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
    # privacy.redact_secrets_before_send: scrub secrets from every outgoing prompt.
    redact_secrets: bool = False
    # privacy.local_only: only providers running on this machine are usable.
    local_only: bool = False


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
        default_model="claude-sonnet-5-5",
        # Ids and prices: Anthropic's models overview (cached 2026-10-06). Release
        # months are approximate: the UI only shows the year.
        models=(
            ModelInfo("claude-fable-5-1", 1_000_000, 10.0, 50.0, "Claude Fable 5.1", "2026-09"),
            ModelInfo("claude-fable-5", 1_000_000, 10.0, 50.0, "Claude Fable 5", "2026-06"),
            ModelInfo("claude-opus-5-5", 1_000_000, 4.0, 20.0, "Claude Opus 5.5", "2026-09"),
            ModelInfo("claude-opus-4-8", 1_000_000, 5.0, 25.0, "Claude Opus 4.8", "2026-05"),
            ModelInfo("claude-sonnet-5-5", 1_000_000, 2.0, 10.0, "Claude Sonnet 5.5", "2026-09"),
            ModelInfo("claude-sonnet-5", 1_000_000, 2.0, 10.0, "Claude Sonnet 5", "2026-04"),
            ModelInfo("claude-haiku-5-5", 1_000_000, 0.1, 0.5, "Claude Haiku 5.5", "2026-10"),
            ModelInfo("claude-haiku-4-5", 200_000, 1.0, 5.0, "Claude Haiku 4.5", "2025-10"),
        ),
    ),
    "openai": ProviderSpec(
        name="openai",
        kind="openai",
        base_url="https://api.openai.com/v1",
        is_local=False,
        default_model="gpt-6.1-terra",
        # developers.openai.com/api/docs/models (2026-11-07). The GPT-5 / GPT-4.1 /
        # GPT-4o / o3 generations are listed there as deprecated and were removed
        # from the picker; GPT-5.6 and 5.5/5.4 are still current.
        models=(
            ModelInfo("gpt-6-astra", 1_050_000, 10.0, 50.0, "GPT-6 Astra", "2026-09"),
            ModelInfo("gpt-6.1-sol", 1_050_000, 2.0, 10.0, "GPT-6.1 Sol", "2026-10"),
            ModelInfo("gpt-6.1-terra", 1_050_000, 1.0, 5.0, "GPT-6.1 Terra", "2026-10"),
            ModelInfo("gpt-6-luna", 1_050_000, 0.1, 0.5, "GPT-6 Luna", "2026-09"),
            ModelInfo("gpt-5.6-sol", 1_000_000, 5.0, 30.0, "GPT-5.6 Sol", "2026-07"),
            ModelInfo("gpt-5.6-terra", 1_000_000, 2.5, 15.0, "GPT-5.6 Terra", "2026-07"),
            ModelInfo("gpt-5.6-luna", 1_000_000, 1.0, 6.0, "GPT-5.6 Luna", "2026-07"),
            ModelInfo("gpt-5.5", 1_000_000, 2.5, 15.0, "GPT-5.5", "2026-05"),
            ModelInfo("gpt-5.4", 1_000_000, 2.5, 15.0, "GPT-5.4", "2026-03"),
        ),
    ),
    "claude-code": ProviderSpec(
        name="claude-code",
        kind="cli",
        base_url="cli://claude",
        is_local=False,
        default_model="default",
        models=(
            ModelInfo("default", 1_000_000, 0.0, 0.0, "Claude Code (défaut)"),
            ModelInfo("claude-fable-5-1", 1_000_000, 0.0, 0.0, "Claude Fable 5.1", "2026-09"),
            ModelInfo("claude-opus-5-5", 1_000_000, 0.0, 0.0, "Claude Opus 5.5", "2026-09"),
            ModelInfo("claude-sonnet-5-5", 1_000_000, 0.0, 0.0, "Claude Sonnet 5.5", "2026-09"),
            ModelInfo("claude-haiku-5-5", 1_000_000, 0.0, 0.0, "Claude Haiku 5.5", "2026-10"),
        ),
    ),
    "codex": ProviderSpec(
        name="codex",
        kind="cli",
        base_url="cli://codex",
        is_local=False,
        default_model="default",
        models=(
            ModelInfo("default", 1_050_000, 0.0, 0.0, "Codex (défaut)"),
            ModelInfo("gpt-6-astra", 1_050_000, 0.0, 0.0, "GPT-6 Astra", "2026-09"),
            ModelInfo("gpt-6.1-sol", 1_050_000, 0.0, 0.0, "GPT-6.1 Sol", "2026-10"),
            ModelInfo("gpt-6.1-terra", 1_050_000, 0.0, 0.0, "GPT-6.1 Terra", "2026-10"),
            ModelInfo("gpt-6-luna", 1_050_000, 0.0, 0.0, "GPT-6 Luna", "2026-09"),
        ),
    ),
    "xai": ProviderSpec(
        name="xai",
        kind="openai",  # xAI exposes an OpenAI-compatible surface
        base_url="https://api.x.ai/v1",
        is_local=False,
        default_model="grok-4.7",
        # docs.x.ai/docs/models (2026-11-07): grok-4.5/4.6/4.7 have a 500k window,
        # grok-4.3 a 1M window. Prices are the <200k-prompt tier.
        models=(
            ModelInfo("grok-4.7", 500_000, 2.0, 6.0, "Grok 4.7", "2026-09"),
            ModelInfo("grok-4.6", 500_000, 2.0, 6.0, "Grok 4.6", "2026-08"),
            ModelInfo("grok-4.5", 500_000, 2.0, 6.0, "Grok 4.5", "2026-07"),
            ModelInfo("grok-4.3", 1_000_000, 1.25, 2.5, "Grok 4.3", "2026-05"),
            ModelInfo("grok-build-0.1", 256_000, 1.0, 2.0, "Grok Build 0.1", "2026-06"),
        ),
    ),
    "google": ProviderSpec(
        name="google",
        kind="openai",  # Gemini exposes an OpenAI-compatible surface (ADR-004)
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        is_local=False,
        # aistudio.google.com/docs/models + /pricing (2026-11-07). Shut down and
        # removed: gemini-3-pro-preview, gemini-3.1-flash-lite-preview, 2.0 family.
        # gemini-2.5-pro/-flash are deprecated (re-routed on 2026-12-01). Prices are
        # the standing ones (gemini-4-argon: $4/$20 from 2026-12-01, promo before;
        # 3.x Flash: $1.50/$7.50 from 2027-01-01, promo before).
        default_model="gemini-3.6-flash",
        models=(
            ModelInfo("gemini-4-argon", 1_000_000, 4.0, 20.0, "Gemini 4 Argon", "2026-10"),
            ModelInfo(
                "gemini-3.1-pro-preview", 1_000_000, 2.0, 12.0, "Gemini 3.1 Pro Preview", "2026-05"
            ),
            ModelInfo("gemini-3.8-flash", 1_000_000, 1.5, 7.5, "Gemini 3.8 Flash", "2026-10"),
            ModelInfo("gemini-3.6-flash", 1_000_000, 1.5, 7.5, "Gemini 3.6 Flash", "2026-07"),
            ModelInfo(
                "gemini-3.5-flash-lite", 1_000_000, 0.3, 2.5, "Gemini 3.5 Flash-Lite", "2026-06"
            ),
            ModelInfo(
                "gemini-3.1-flash-lite", 1_000_000, 0.25, 1.5, "Gemini 3.1 Flash-Lite", "2026-06"
            ),
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
        # api-docs.deepseek.com (2026-11-07): the id is now "deepseek-flash" (served
        # by DeepSeek-V4.1-Flash-1017); "deepseek-v4-flash" is a retired legacy alias
        # that is merely re-routed, so it is no longer offered. Prices are the last
        # published ones (the pricing page was not readable) and only drive the
        # "$" badge.
        default_model="deepseek-flash",
        models=(
            ModelInfo("deepseek-flash", 1_000_000, 0.14, 0.28, "DeepSeek V4.1 Flash", "2026-09"),
            ModelInfo("deepseek-v4-pro", 1_000_000, 0.44, 0.87, "DeepSeek V4 Pro", "2026-03"),
        ),
    ),
    "mistral": ProviderSpec(
        name="mistral",
        kind="openai",
        base_url="https://api.mistral.ai/v1",
        is_local=False,
        # docs.mistral.ai (2026-11-07) lists Mistral Large 4 (v26.10), Small 4
        # (v26.03) and Codestral (v25.08). Ids stay on the "-latest" rolling aliases
        # so they keep following new dated releases.
        default_model="mistral-medium-latest",
        models=(
            ModelInfo("mistral-large-latest", 256_000, 0.5, 1.5, "Mistral Large 4", "2026-10"),
            ModelInfo("mistral-medium-latest", 131_072, 0.4, 2.0, "Mistral Medium", "2026-01"),
            ModelInfo("mistral-small-latest", 131_072, 0.1, 0.3, "Mistral Small 4", "2026-03"),
            ModelInfo("codestral-latest", 256_000, 0.3, 0.9, "Codestral", "2025-08"),
        ),
    ),
}

_MODEL_TIERS: dict[str, Tier] = {
    # anthropic
    "claude-fable-5-1": "powerful",
    "claude-fable-5": "powerful",
    "claude-opus-5-5": "powerful",
    "claude-opus-4-8": "powerful",
    "claude-sonnet-5-5": "balanced",
    "claude-sonnet-5": "balanced",
    "claude-haiku-5-5": "fast",
    "claude-haiku-4-5": "fast",
    # openai
    "gpt-6-astra": "powerful",
    "gpt-6.1-sol": "powerful",
    "gpt-6.1-terra": "balanced",
    "gpt-6-luna": "fast",
    "gpt-5.6-sol": "powerful",
    "gpt-5.6-terra": "balanced",
    "gpt-5.6-luna": "fast",
    "gpt-5.5": "balanced",
    "gpt-5.4": "balanced",
    # xai
    "grok-4.7": "powerful",
    "grok-4.6": "powerful",
    "grok-4.5": "powerful",
    "grok-4.3": "balanced",
    "grok-build-0.1": "fast",
    # google
    "gemini-4-argon": "powerful",
    "gemini-3.1-pro-preview": "powerful",
    "gemini-3.8-flash": "balanced",
    "gemini-3.6-flash": "balanced",
    "gemini-3.5-flash-lite": "fast",
    "gemini-3.1-flash-lite": "fast",
    # CLI providers: "default" = whatever model the user's own CLI is set to.
    "default": "balanced",
    # local fallbacks
    "llama3.1:8b": "fast",
    "qwen2.5-coder:14b": "balanced",
    # deepseek
    "deepseek-flash": "balanced",
    "deepseek-v4-pro": "powerful",
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
        # CLI-backed providers need no key: they are usable once the vendor CLI
        # is installed (sign-in state is checked by ``probe``, not here, so
        # this stays cheap and synchronous).
        if spec.kind == "cli":
            return find_binary(CLI_BINARIES[spec.name]) is not None
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
        call = call or ProviderCallConfig()
        if call.local_only and not spec.is_local:
            return None  # privacy: nothing may leave this machine
        provider = self._build_raw(spec, cache, call)
        if provider is not None and call.redact_secrets:
            return RedactingProvider(provider)
        return provider

    def _build_raw(
        self, spec: ProviderSpec, cache: "PromptCacheConfig | None", call: ProviderCallConfig
    ) -> ModelProvider | None:
        if spec.kind == "cli":
            cli_kwargs: dict[str, Any] = {
                "name": spec.name,
                "base_url": spec.base_url,
                "default_model": spec.default_model,
                "models": spec.models,
                "timeout_s": call.timeout_s,
            }
            if spec.name == "claude-code":
                return ClaudeCodeProvider(**cli_kwargs)
            return CodexProvider(**cli_kwargs)
        api_key = self._secrets.get(spec.name)
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
        """Connectivity test against the models-list endpoint -> (reachable, detail).

        For CLI-backed providers "reachable" means installed **and signed in**.
        """
        if spec.kind == "cli":
            return await self.cli_status(spec.name)
        url = _models_list_url(spec)
        try:
            async with _probe_client_or_default(self.probe_client) as client:
                response = await client.get(url, headers=self._probe_headers(spec))
        except httpx.HTTPError as exc:
            return False, f"{type(exc).__name__}: {exc}"
        if response.status_code == 200:
            return True, None
        return False, f"HTTP {response.status_code}: {response.text[:200]}"

    async def cli_state(self, name: str) -> tuple[bool, str | None, dict[str, Any] | None]:
        """``(signed_in, detail, account)`` for a CLI-backed provider."""
        if name == "claude-code":
            return await claude_code.auth_state()
        if name == "codex":
            return await codex_cli.auth_state()
        return False, f"'{name}' is not a CLI provider", None

    async def cli_status(self, name: str) -> tuple[bool, str | None]:
        """``(signed_in, detail)`` for a CLI-backed provider."""
        signed_in, detail, _ = await self.cli_state(name)
        return signed_in, detail

    async def cli_logout(self, name: str) -> tuple[bool, str]:
        """Sign the vendor CLI out. NOTE: the CLI session is machine-wide, so this
        also signs the user out of that CLI in their terminal."""
        import asyncio

        from elysium_engine.providers.cli_common import run_blocking

        if name == "claude-code":
            argv = claude_code.logout_argv()
            # An imported token lives in the keychain: signing out removes it too.
            with contextlib.suppress(Exception):
                self._secrets.delete(CLAUDE_TOKEN_KEY)
        elif name == "codex":
            argv = codex_cli.logout_argv()
        else:
            raise ProviderError(f"'{name}' is not a CLI provider")
        code, text = await asyncio.to_thread(run_blocking, argv)
        return code == 0, text.strip()[:200]

    # --- imported (pasted) sign-in tokens -------------------------------------

    async def verify_claude_token(self, token: str) -> tuple[bool, str | None]:
        return await claude_code.verify_token(token)

    def keep_claude_token(self, token: str | None) -> str | None:
        """Store (or, with ``None``, remove) the pasted Claude token; returns the previous one."""
        previous = self._secrets.get(CLAUDE_TOKEN_KEY)
        if token is None:
            with contextlib.suppress(Exception):
                self._secrets.delete(CLAUDE_TOKEN_KEY)
        else:
            self._secrets.set(CLAUDE_TOKEN_KEY, token)
        return previous

    def cli_login_argv(self, name: str, mode: str = "browser") -> list[str]:
        """Command that signs a CLI provider in with the user's own account."""
        if name == "claude-code":
            return claude_code.login_argv(mode=mode)
        if name == "codex":
            return codex_cli.login_argv(mode=mode)
        raise ProviderError(f"'{name}' is not a CLI provider")

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

    def health(self, spec: ProviderSpec) -> "Health":
        from elysium_engine.providers.health import LEDGER

        return LEDGER.health(spec.name, kind=spec.kind, configured=self.is_configured(spec))

    def available_options(
        self, records: Sequence[ProviderRecord], local_only: bool = False
    ) -> list[ModelOption]:
        """Routable (provider, model) options for :func:`routing.select_model`."""
        options: list[ModelOption] = []
        for record in records:
            spec = spec_for(record)
            if not self.is_configured(spec):
                continue
            if local_only and not spec.is_local:
                continue
            # "Installed" / "key saved" is not "can answer": skip providers that
            # are signed out, rejected, or out of quota (reported, not silent).
            if not self.health(spec).usable:
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
