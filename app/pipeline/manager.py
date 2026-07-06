"""PipelineManager owns capture threads, the inference worker, and publishers.

Reconciles running state to DB config on every camera CRUD.
"""
from __future__ import annotations

import json
import logging
import threading

from app.db import get_conn
from app.pipeline.capture import CameraConfig, CaptureWorker
from app.pipeline.frame_bus import FrameBus

logger = logging.getLogger("snvr.pipeline")


class PipelineManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.bus = FrameBus()
        self._captures: dict[int, CaptureWorker] = {}
        self._inference = None
        self.publishers: list = []

    async def start(self) -> None:
        logger.info("PipelineManager starting")
        # Late import to avoid loading Ultralytics/torch until needed
        from app.pipeline.inference import InferenceWorker
        from app.events.ws_broadcaster import WSBroadcaster
        from app.events.sqlite_sink import SQLiteSink
        from app.events.snapshot_store import SnapshotStore

        self.snapshot_store = SnapshotStore()
        self.ws_broadcaster = WSBroadcaster()
        self.sqlite_sink = SQLiteSink()
        self.publishers = [self.sqlite_sink, self.ws_broadcaster]

        from app.settings import settings as _settings
        self._mqtt_publisher = None
        if _settings.mqtt_host:
            from app.events.mqtt_publisher import MQTTPublisher
            self._mqtt_publisher = MQTTPublisher()
            self._mqtt_publisher.connect()
            self.publishers.append(self._mqtt_publisher)

        self._inference = InferenceWorker(
            self.bus, self.publishers, self.snapshot_store
        )
        self._inference.start()
        self.reconcile()

    async def stop(self) -> None:
        logger.info("PipelineManager stopping")
        with self._lock:
            for w in self._captures.values():
                w.stop()
            self._captures.clear()
        if self._inference is not None:
            self._inference.stop()
            self._inference = None
        if self._mqtt_publisher is not None:
            self._mqtt_publisher.disconnect()
            self._mqtt_publisher = None

    def reconcile(self) -> None:
        """Sync running capture threads to DB camera list."""
        conn = get_conn()
        rows = conn.execute("SELECT * FROM cameras").fetchall()
        wanted: dict[int, CameraConfig] = {}
        for r in rows:
            wanted[r["id"]] = CameraConfig(
                camera_id=r["id"],
                name=r["name"],
                rtsp_url=r["rtsp_url"],
                target_fps=r["target_fps"],
                enabled=bool(r["enabled"]),
            )

        with self._lock:
            existing = set(self._captures)
            for cam_id in existing - wanted.keys():
                logger.info("removing capture for camera %d", cam_id)
                self._captures[cam_id].stop()
                del self._captures[cam_id]
                self.bus.drop_camera(cam_id)

            for cam_id, cfg in wanted.items():
                if cam_id in self._captures:
                    self._captures[cam_id].update_config(cfg)
                    continue
                worker = CaptureWorker(cfg, self.bus)
                self._captures[cam_id] = worker
                if cfg.enabled:
                    worker.start()
                    logger.info("started capture for camera %d (%s)", cam_id, cfg.name)

            if self._inference is not None:
                self._inference.set_camera_configs(wanted)

    def status(self) -> list[dict]:
        with self._lock:
            return [w.status for w in self._captures.values()]
