"""Bounded frame queue for inference + per-camera latest-frame cache for preview/snapshot."""
from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

from app.settings import settings


@dataclass
class Frame:
    camera_id: int
    ts: float
    bgr: np.ndarray


class FrameBus:
    """One inference queue shared across cameras + a per-camera latest-frame cache."""

    def __init__(self, max_queue: Optional[int] = None) -> None:
        self.inference_q: queue.Queue[Frame] = queue.Queue(
            maxsize=max_queue or settings.frame_queue_max
        )
        self._latest: dict[int, tuple[float, np.ndarray]] = {}
        self._latest_jpeg: dict[int, tuple[float, bytes]] = {}
        self._lock = threading.Lock()

    def submit(self, frame: Frame, for_inference: bool) -> None:
        with self._lock:
            self._latest[frame.camera_id] = (frame.ts, frame.bgr)
            self._latest_jpeg.pop(frame.camera_id, None)
        if for_inference:
            try:
                self.inference_q.put_nowait(frame)
            except queue.Full:
                try:
                    self.inference_q.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self.inference_q.put_nowait(frame)
                except queue.Full:
                    pass

    def take(self, timeout: float = 1.0) -> Optional[Frame]:
        try:
            return self.inference_q.get(timeout=timeout)
        except queue.Empty:
            return None

    def latest_bgr(self, camera_id: int) -> Optional[tuple[float, np.ndarray]]:
        with self._lock:
            return self._latest.get(camera_id)

    def latest_jpeg(self, camera_id: int, quality: int = 80) -> Optional[tuple[float, bytes]]:
        with self._lock:
            cached = self._latest_jpeg.get(camera_id)
            if cached is not None:
                return cached
            entry = self._latest.get(camera_id)
        if entry is None:
            return None
        ts, bgr = entry
        ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if not ok:
            return None
        jpeg = bytes(buf)
        with self._lock:
            self._latest_jpeg[camera_id] = (ts, jpeg)
        return ts, jpeg

    def drop_camera(self, camera_id: int) -> None:
        with self._lock:
            self._latest.pop(camera_id, None)
            self._latest_jpeg.pop(camera_id, None)
