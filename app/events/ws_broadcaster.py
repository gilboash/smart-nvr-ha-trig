"""Fan-out episode events to connected /ws/events subscribers."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict

from fastapi import WebSocket

from app.events.publisher import EpisodeEvent, EventPublisher

logger = logging.getLogger("snvr.ws")


class WSBroadcaster(EventPublisher):
    def __init__(self) -> None:
        self._subscribers: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def add(self, ws: WebSocket) -> None:
        async with self._lock:
            self._subscribers.add(ws)

    async def remove(self, ws: WebSocket) -> None:
        async with self._lock:
            self._subscribers.discard(ws)

    async def publish(self, event: EpisodeEvent) -> None:
        payload = asdict(event)
        dead: list[WebSocket] = []
        async with self._lock:
            subs = list(self._subscribers)
        for ws in subs:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._subscribers.discard(ws)
