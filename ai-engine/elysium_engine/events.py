"""In-process event bus bridging agent runs to SSE subscribers.

Events are persisted first (append-only ``events`` table, ADR-005) and then
published here so live SSE streams receive them without polling.  Replay after
reconnect reads straight from the database using the event id as cursor.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

BusEvent = dict[str, Any]  # {"id": int, "type": str, "payload": dict, "agent": str | None}


class EventBus:
    def __init__(self) -> None:
        self._subscribers: defaultdict[str, set[asyncio.Queue[BusEvent]]] = defaultdict(set)

    def subscribe(self, conversation_id: str) -> asyncio.Queue[BusEvent]:
        queue: asyncio.Queue[BusEvent] = asyncio.Queue()
        self._subscribers[conversation_id].add(queue)
        return queue

    def unsubscribe(self, conversation_id: str, queue: asyncio.Queue[BusEvent]) -> None:
        self._subscribers[conversation_id].discard(queue)
        if not self._subscribers[conversation_id]:
            self._subscribers.pop(conversation_id, None)

    def publish(self, conversation_id: str, event: BusEvent) -> None:
        for queue in list(self._subscribers.get(conversation_id, ())):
            queue.put_nowait(event)
