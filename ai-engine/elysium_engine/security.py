"""Bearer-token authentication for every route except ``/health``.

The token is generated per-session by the Rust core (ARCHITECTURE.md §2).
Comparison is constant-time to avoid timing side channels.
"""

from __future__ import annotations

import secrets

from fastapi import HTTPException, Request, status


def require_token(request: Request) -> None:
    """FastAPI dependency: reject requests without a valid Bearer token.

    Attached at router level to all routers except the health router.
    """
    expected: str = request.app.state.settings.token
    header = request.headers.get("authorization", "")
    scheme, _, raw = header.partition(" ")
    provided = raw.strip()
    # An empty value must never match, even if the expected token were empty.
    token_ok = bool(provided) and secrets.compare_digest(provided.encode(), expected.encode())
    if scheme.lower() != "bearer" or not token_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
