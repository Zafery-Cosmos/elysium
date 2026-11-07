"""Usage recording: one row per model call (feeds the admin dashboard).

Recording must never break a chat: every failure here is logged and swallowed.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from elysium_engine.db.models import Conversation, UsageRecord

log = logging.getLogger(__name__)


def record_usage(
    session_factory: sessionmaker[Session],
    *,
    provider: str,
    model: str,
    agent_name: str | None,
    conversation_id: str | None,
    usage: Mapping[str, Any],
    duration_ms: int,
    status: str = "ok",
    error: str | None = None,
) -> None:
    try:
        with session_factory() as session:
            project_id: str | None = None
            if conversation_id is not None:
                conversation = session.get(Conversation, conversation_id)
                project_id = conversation.project_id if conversation is not None else None
            session.add(
                UsageRecord(
                    provider=provider,
                    model=model,
                    agent_name=agent_name,
                    project_id=project_id,
                    conversation_id=conversation_id,
                    input_tokens=int(usage.get("input_tokens") or 0),
                    output_tokens=int(usage.get("output_tokens") or 0),
                    cost_usd=usage.get("cost_usd"),
                    duration_ms=max(0, int(duration_ms)),
                    status=status,
                    error=(error or None) and error[:500],
                )
            )
            session.commit()
    except Exception:  # noqa: BLE001 - usage logging must never break a chat
        log.exception("could not record usage for %s/%s", provider, model)
