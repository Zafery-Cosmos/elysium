"""Usage recording: one row per model call (feeds the admin dashboard).

Recording must never break a chat: every failure here is logged and swallowed.
Writes are idempotent per ``request_id``: replaying the same call (a retry, a
duplicated event) never double-counts.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from elysium_engine.costing import billing_for, current_rate, figures_for
from elysium_engine.db.models import Conversation, UsageRecord

log = logging.getLogger(__name__)


def new_request_id() -> str:
    return uuid.uuid4().hex


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
    request_id: str | None = None,
) -> bool:
    """Persist one call. Returns False when it was already recorded (or failed)."""
    request_id = request_id or new_request_id()
    try:
        quote = current_rate(session_factory)
        figures = figures_for(provider, model, dict(usage), quote) if status == "ok" else None
        with session_factory() as session:
            if session.scalar(select(UsageRecord.id).where(UsageRecord.request_id == request_id)):
                return False
            project_id: str | None = None
            if conversation_id is not None:
                conversation = session.get(Conversation, conversation_id)
                project_id = conversation.project_id if conversation is not None else None
            session.add(
                UsageRecord(
                    request_id=request_id,
                    provider=provider,
                    model=model,
                    agent_name=agent_name,
                    project_id=project_id,
                    conversation_id=conversation_id,
                    input_tokens=int(usage.get("input_tokens") or 0),
                    output_tokens=int(usage.get("output_tokens") or 0),
                    cache_read_tokens=int(usage.get("cache_read_tokens") or 0),
                    cache_write_tokens=int(usage.get("cache_write_tokens") or 0),
                    billing=figures.billing if figures else billing_for(provider),
                    cost_kind=figures.kind if figures else "none",
                    cost_usd=figures.cost_usd if figures else None,
                    cost_eur=figures.cost_eur if figures else None,
                    fx_rate=figures.fx_rate if figures else None,
                    duration_ms=max(0, int(duration_ms)),
                    status=status,
                    error=(error or None) and error[:500],
                )
            )
            try:
                session.commit()
            except IntegrityError:  # concurrent replay of the same request_id
                session.rollback()
                return False
            return True
    except Exception:  # noqa: BLE001 - usage logging must never break a chat
        log.exception("could not record usage for %s/%s", provider, model)
        return False
