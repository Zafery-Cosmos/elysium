"""Secret redaction for outgoing prompts (privacy.redact_secrets_before_send).

Applied by :class:`RedactingProvider` right before a message leaves the
machine, whichever provider receives it.  Pattern-based and deliberately
conservative: it catches well-known key formats and ``key=value`` assignments,
not every possible secret.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Sequence

from elysium_engine.providers.base import (
    ChatMessage,
    Chunk,
    Effort,
    ModelInfo,
    ModelProvider,
    ToolSpec,
)

REDACTED = "[REDACTED]"

_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL
    ),
    re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{20,}"),
)

# key = value / "key": "value" -> keep the key, hide the value.
_ASSIGNMENT = re.compile(
    r"""(?ix)
    (\b(?:api[_-]?key|secret|token|password|passwd|private[_-]?key)\b["']?\s*[:=]\s*)
    (["']?)([^\s"']{8,})\2
    """
)


def redact_secrets(text: str) -> str:
    for pattern in _PATTERNS:
        text = pattern.sub(REDACTED, text)
    return _ASSIGNMENT.sub(lambda m: f"{m.group(1)}{REDACTED}", text)


class RedactingProvider(ModelProvider):
    """Wraps any provider and scrubs secrets from every message it is sent."""

    def __init__(self, inner: ModelProvider) -> None:
        self._inner = inner
        self.name = inner.name
        self.base_url = inner.base_url
        self.default_model = inner.default_model

    def models(self) -> Sequence[ModelInfo]:
        return self._inner.models()

    async def is_reachable(self) -> bool:
        return await self._inner.is_reachable()

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec] | None = None,
        stream: bool = False,
        model: str | None = None,
        effort: Effort | None = None,
    ) -> AsyncIterator[Chunk]:
        clean = [{"role": m["role"], "content": redact_secrets(m["content"])} for m in messages]
        async for chunk in self._inner.chat(
            clean, tools, stream=stream, model=model, effort=effort  # type: ignore[arg-type]
        ):
            yield chunk
