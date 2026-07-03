"""Per-camera capture thread: drains RTSP, gates by target FPS, updates frame bus."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Optional

import cv2

from app.pipeline.frame_bus import Frame, FrameBus

logger = logging.getLogger("snvr.capture")


@dataclass
class CameraConfig:
    camera_id: int
    name: str
    rtsp_url: str
    target_fps: float
    enabled: bool


class CaptureWorker:
    """Continuously reads RTSP frames in a thread. Gates enqueue by target_fps.

    Always keeps latest-frame cache updated even when target_fps == 0
    (used for snapshots and preview).
    """

    _RECONNECT_BASE_S = 1.0
    _RECONNECT_MAX_S = 30.0

    def __init__(self, cfg: CameraConfig, bus: FrameBus) -> None:
        self.cfg = cfg
        self.bus = bus
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._status: str = "starting"
        self._last_error: Optional[str] = None
        self._last_frame_ts: float = 0.0

    @property
    def status(self) -> dict:
        return {
            "camera_id": self.cfg.camera_id,
            "status": self._status,
            "last_error": self._last_error,
            "last_frame_ts": self._last_frame_ts,
        }

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name=f"cap-{self.cfg.camera_id}", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def update_config(self, cfg: CameraConfig) -> None:
        """Called when the camera's row changed. If URL/enabled changed, restart."""
        needs_restart = (
            cfg.rtsp_url != self.cfg.rtsp_url
            or cfg.enabled != self.cfg.enabled
        )
        self.cfg = cfg
        if needs_restart:
            self.stop()
            if cfg.enabled:
                self.start()

    def _run(self) -> None:
        backoff = self._RECONNECT_BASE_S
        while not self._stop.is_set():
            if not self.cfg.enabled:
                self._status = "disabled"
                self._stop.wait(1.0)
                continue

            cap = cv2.VideoCapture(self.cfg.rtsp_url, cv2.CAP_FFMPEG)
            if not cap.isOpened():
                self._status = "disconnected"
                self._last_error = "could not open stream"
                logger.warning("camera %s: open failed, retry in %.1fs", self.cfg.name, backoff)
                self._stop.wait(backoff)
                backoff = min(backoff * 2, self._RECONNECT_MAX_S)
                continue

            self._status = "connected"
            self._last_error = None
            backoff = self._RECONNECT_BASE_S
            logger.info("camera %s: connected", self.cfg.name)

            last_enqueue = 0.0
            try:
                while not self._stop.is_set():
                    ok, frame = cap.read()
                    if not ok or frame is None:
                        self._status = "disconnected"
                        self._last_error = "read failed"
                        logger.warning("camera %s: read failed, reconnecting", self.cfg.name)
                        break

                    now = time.time()
                    self._last_frame_ts = now

                    for_inference = False
                    if self.cfg.target_fps > 0:
                        interval = 1.0 / self.cfg.target_fps
                        if now - last_enqueue >= interval:
                            for_inference = True
                            last_enqueue = now

                    self.bus.submit(Frame(self.cfg.camera_id, now, frame), for_inference)
            finally:
                cap.release()
