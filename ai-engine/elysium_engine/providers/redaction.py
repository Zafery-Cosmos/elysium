"""Secret redaction for outgoing prompts (privacy.redact_secrets_before_send).

Applied by :class:`RedactingProvider` right before a message leaves the
machine, whichever provider receives it.  Pattern-based: it catches well-known
key formats, credentials embedded in URLs and ``key=value`` assignments, not
every possible secret.
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
    # A block cut off before its END line (truncated paste) is still a key.
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY(?: BLOCK)?-----.*?"
        r"(?:-----END [A-Z ]*PRIVATE KEY(?: BLOCK)?-----|\Z)",
        re.DOTALL,
    ),
    re.compile(r"(?<![A-Za-z0-9])sk-ant-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"(?<![A-Za-z0-9])[sr]k_(?:live|test)_[A-Za-z0-9]{16,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}"),
    re.compile(r"\bglpat-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bhf_[A-Za-z0-9]{30,}"),
    re.compile(r"\bnpm_[A-Za-z0-9]{30,}"),
    re.compile(r"\bya29\.[A-Za-z0-9_\-]{20,}"),
    re.compile(r"\bSG\.[A-Za-z0-9_\-]{16,}\.[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"),
    # JSON Web Tokens: three base64url parts, the first two starting with "eyJ".
    re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-+/=]{16,}"),
    re.compile(r"(?i)\bBasic\s+[A-Za-z0-9+/]{8,}={0,2}"),
)

# scheme://user:password@host -> the host stays readable, the password does not.
_URL_CREDENTIALS = re.compile(r"(\b[a-zA-Z][a-zA-Z0-9+.\-]*://[^\s:/@]*:)([^\s/@]+)(@)")

# key = value / "key": "value" -> keep the key, hide the value. The keyword may
# sit inside a longer name (AWS_SECRET_ACCESS_KEY, DB_PASSWORD, access_token).
_KEY = (
    r"[A-Za-z0-9_.\-]*"
    r"(?:api[_-]?key|access[_-]?key|private[_-]?key|secret|password|passwd|pwd|credential|token(?!s\b))"
    r"[A-Za-z0-9_.\-]*"
)
_ASSIGNMENT = re.compile(
    rf"""(?ix)
    (?<![A-Za-z0-9_.\-])
    ({_KEY}["']?\s*[:=]\s*)
    (?:
        "(?P<dq>[^"\n]{{8,}})"
      | '(?P<sq>[^'\n]{{8,}})'
      | (?P<bare>[^\s"',;]{{8,}})
    )
    """
)


def _hide_value(match: re.Match[str]) -> str:
    value = match["dq"] or match["sq"] or match["bare"]
    # Counters such as token_count: 12345678 are not secrets.
    if value.isdigit():
        return match.group(0)
    quote = '"' if match["dq"] else "'" if match["sq"] else ""
    return f"{match.group(1)}{quote}{REDACTED}{quote}"


def redact_secrets(text: str) -> str:
    for pattern in _PATTERNS:
        text = pattern.sub(REDACTED, text)
    text = _URL_CREDENTIALS.sub(lambda m: f"{m.group(1)}{REDACTED}{m.group(3)}", text)
    return _ASSIGNMENT.sub(_hide_value, text)


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
