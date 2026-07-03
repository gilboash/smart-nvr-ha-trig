"""Writes JPEG snapshots for episode ENTER frames."""
from __future__ import annotations

import logging
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
