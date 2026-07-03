"""EventPublisher that persists episodes to SQLite."""
from __future__ import annotations

import logging

from app.db import tx
from app.events.publisher import EpisodeEvent, EventPublisher

logger = logging.getLogger("snvr.sink")


class SQLiteSink(EventPublisher):
    async def publish(self, event: EpisodeEvent) -> None:
        # Episode rows are created/updated by the aggregator directly (needs the id).
        # This sink is mostly here so Phase 2 has a consistent publisher API to hook.
        # Kept minimal by design.
        logger.debug("event %s episode=%d cam=%d cls=%s", event.kind, event.episode_id, event.camera_id, event.class_name)


def create_episode(camera_id: int, zone_id: int | None, class_name: str,
                   start_ts: float, max_confidence: float,
                   snapshot_path: str | None) -> int:
    with tx() as conn:
        cur = conn.execute(
            """
            INSERT INTO episodes (camera_id, zone_id, class_name, start_ts,
                                  max_confidence, frame_count, snapshot_path)
            VALUES (?, ?, ?, ?, ?, 1, ?)
            """,
            (camera_id, zone_id, class_name, start_ts, max_confidence, snapshot_path),
        )
        return int(cur.lastrowid)


def bump_episode(episode_id: int, end_ts: float, max_confidence: float) -> None:
    with tx() as conn:
        conn.execute(
            """
            UPDATE episodes
               SET end_ts = ?,
                   frame_count = frame_count + 1,
                   max_confidence = MAX(max_confidence, ?)
             WHERE id = ?
            """,
            (end_ts, max_confidence, episode_id),
        )


def close_episode(episode_id: int, end_ts: float) -> None:
    with tx() as conn:
        conn.execute("UPDATE episodes SET end_ts = ? WHERE id = ?", (end_ts, episode_id))


def set_episode_snapshot(episode_id: int, path: str) -> None:
    with tx() as conn:
        conn.execute("UPDATE episodes SET snapshot_path = ? WHERE id = ?", (path, episode_id))
