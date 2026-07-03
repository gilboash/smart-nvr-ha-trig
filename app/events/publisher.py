"""EventPublisher ABC — Phase 2 seam.

Phase 1 publishers: SQLiteSink, WSBroadcaster.
Phase 2 will add MQTTPublisher / WebhookPublisher and register them in PipelineManager.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal, Optional


EventKind = Literal["ENTER", "EXIT"]


@dataclass
class EpisodeEvent:
    kind: EventKind
    episode_id: int
    camera_id: int
    zone_id: Optional[int]
    class_name: str
    ts: float
    confidence: float
    snapshot_path: Optional[str] = None


class EventPublisher(ABC):
    @abstractmethod
    async def publish(self, event: EpisodeEvent) -> None: ...
