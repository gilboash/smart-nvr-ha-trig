"""Episode aggregation with hysteresis.

Per (camera_id, class_name, zone_id) key:
- On first detection: open a new episode row, emit ENTER.
- On subsequent detections within hysteresis_s: update end_ts and confidence.
- On timeout (no detection for hysteresis_s): close row, emit EXIT.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Optional

from app.events.publisher import EpisodeEvent
from app.events.sqlite_sink import (
    bump_episode,
    close_episode,
    create_episode,
    set_episode_snapshot,
)

logger = logging.getLogger("snvr.agg")

EpisodeKey = tuple[int, str, Optional[int]]  # camera_id, class_name, zone_id


@dataclass
class _OpenEpisode:
    episode_id: int
    last_ts: float
    max_confidence: float


class EpisodeAggregator:
    def __init__(self) -> None:
        self._open: dict[EpisodeKey, _OpenEpisode] = {}
        self._lock = threading.Lock()

    def observe(
        self,
        camera_id: int,
        class_name: str,
        zone_id: Optional[int],
        confidence: float,
        ts: float,
        snapshot_saver=None,  # callable(episode_id) -> Optional[str]
    ) -> tuple[Optional[EpisodeEvent], _OpenEpisode]:
        key: EpisodeKey = (camera_id, class_name, zone_id)
        with self._lock:
            existing = self._open.get(key)
            if existing is None:
                episode_id = create_episode(
                    camera_id=camera_id,
                    zone_id=zone_id,
                    class_name=class_name,
                    start_ts=ts,
                    max_confidence=confidence,
                    snapshot_path=None,
                )
                snapshot_path: Optional[str] = None
                if snapshot_saver is not None:
                    snapshot_path = snapshot_saver(episode_id)
                    if snapshot_path is not None:
                        set_episode_snapshot(episode_id, snapshot_path)
                ep = _OpenEpisode(episode_id=episode_id, last_ts=ts, max_confidence=confidence)
                self._open[key] = ep
                logger.info("episode ENTER cam=%d cls=%s zone=%s id=%d", camera_id, class_name, zone_id, episode_id)
                return (
                    EpisodeEvent(
                        kind="ENTER",
                        episode_id=episode_id,
                        camera_id=camera_id,
                        zone_id=zone_id,
                        class_name=class_name,
                        ts=ts,
                        confidence=confidence,
                        snapshot_path=snapshot_path,
                    ),
                    ep,
                )
            existing.last_ts = ts
            existing.max_confidence = max(existing.max_confidence, confidence)
            bump_episode(existing.episode_id, ts, confidence)
            return None, existing

    def sweep(self, now_ts: float, hysteresis_for_camera) -> list[EpisodeEvent]:
        """Close any open episode whose (now - last_ts) exceeds its camera's hysteresis.

        hysteresis_for_camera: callable(camera_id) -> float seconds.
        """
        events: list[EpisodeEvent] = []
        with self._lock:
            expired: list[EpisodeKey] = []
            for key, ep in self._open.items():
                camera_id = key[0]
                hyst = hysteresis_for_camera(camera_id)
                if now_ts - ep.last_ts >= hyst:
                    expired.append(key)
            for key in expired:
                ep = self._open.pop(key)
                close_episode(ep.episode_id, ep.last_ts)
                logger.info("episode EXIT id=%d", ep.episode_id)
                events.append(
                    EpisodeEvent(
                        kind="EXIT",
                        episode_id=ep.episode_id,
                        camera_id=key[0],
                        zone_id=key[2],
                        class_name=key[1],
                        ts=ep.last_ts,
                        confidence=ep.max_confidence,
                    )
                )
        return events
