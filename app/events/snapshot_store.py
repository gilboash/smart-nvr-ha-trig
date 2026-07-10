"""Writes JPEG snapshots for episode ENTER frames."""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import cv2
import numpy as np

from app.settings import settings

logger = logging.getLogger("snvr.snapshot")


class SnapshotStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or settings.snapshot_dir)
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, episode_id: int) -> Path:
        return self.root / f"{episode_id}.jpg"

    def save(self, episode_id: int, bgr: np.ndarray, quality: int = 85) -> str | None:
        path = self.path_for(episode_id)
        ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if not ok:
            logger.warning("imencode failed for episode %d", episode_id)
            return None
        path.write_bytes(bytes(buf))
        return str(path)

    def cleanup_old(self) -> int:
        max_age = settings.snapshot_max_age_days
        if max_age <= 0:
            return 0
        from app.db import get_conn, tx
        cutoff = time.time() - max_age * 86400
        rows = get_conn().execute(
            "SELECT id, snapshot_path FROM episodes WHERE start_ts < ? AND snapshot_path IS NOT NULL",
            (cutoff,),
        ).fetchall()
        if not rows:
            return 0
        count = 0
        for r in rows:
            try:
                os.remove(r["snapshot_path"])
            except OSError:
                pass
            with tx() as conn:
                conn.execute("UPDATE episodes SET snapshot_path = NULL WHERE id = ?", (r["id"],))
            count += 1
        logger.info("snapshot cleanup: removed %d snapshots older than %d days", count, max_age)
        return count
