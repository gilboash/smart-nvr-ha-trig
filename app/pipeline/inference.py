"""Inference worker: single shared YOLO model + optional CLIP state classifier.

YOLO handles object detection zones; CLIP handles state classification zones
(e.g. curtain open/closed). Both run in the same thread to avoid GPU contention.
"""
from __future__ import annotations

import asyncio
import copy
import logging
import threading
import time
from typing import Optional

import torch

from app.pipeline.aggregator import EpisodeAggregator
from app.pipeline.capture import CameraConfig
from app.pipeline.clip_classifier import CLIPClassifier, crop_zone
from app.pipeline.filters import load_zones, match_zone
from app.pipeline.frame_bus import Frame, FrameBus
from app.pipeline.overlay import Detection
from app.settings import settings

logger = logging.getLogger("snvr.infer")

_STATE_CHECK_INTERVAL = 1.0  # seconds between CLIP classifications per zone


def _resolve_device(pref: str) -> str:
    if pref == "auto":
        return "cuda:0" if torch.cuda.is_available() else "cpu"
    return pref


class InferenceWorker:
    def __init__(self, bus: FrameBus, publishers: list, snapshot_store) -> None:
        self.bus = bus
        self.publishers = publishers
        self.snapshot_store = snapshot_store
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._sweep_thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._camera_configs: dict[int, CameraConfig] = {}
        self._camera_classes: dict[int, set[str]] = {}
        self._camera_hysteresis: dict[int, float] = {}
        self._zone_cache: dict[int, list] = {}
        self._zone_cache_ts: dict[int, float] = {}
        self._latest_detections: dict[int, list[Detection]] = {}
        self._latest_detections_ts: dict[int, float] = {}
        self._detections_lock = threading.Lock()
        # State classification (CLIP)
        self._state_last_ts: dict[int, float] = {}      # zone_id → last check ts
        self._state_last_label: dict[int, str] = {}     # zone_id → last label
        self._state_latest: dict[int, tuple[str, float, list]] = {}  # zone_id → (label, prob, ranked)
        self._state_lock = threading.Lock()
        self.aggregator = EpisodeAggregator()

        self.device = _resolve_device(settings.device)
        self._model = None
        self._model_class_names: dict[int, str] = {}
        self._clip: Optional[CLIPClassifier] = None

    def _load_model(self, weights: str = "yolov8n.pt"):
        from ultralytics import YOLO
        model_path = settings.model_dir / weights
        target = str(model_path) if model_path.exists() else weights
        logger.info("loading YOLO model %s on device %s", target, self.device)
        model = YOLO(target)
        try:
            model.to(self.device)
        except Exception as e:
            logger.warning("model.to(%s) failed: %s — falling back to CPU", self.device, e)
            self.device = "cpu"
            model.to("cpu")
        self._model = model
        self._model_class_names = dict(model.names) if hasattr(model, "names") else {}
        logger.info("inference device = %s, classes = %d", self.device, len(self._model_class_names))

    def _ensure_clip(self) -> CLIPClassifier:
        if self._clip is None:
            self._clip = CLIPClassifier(device=self.device)
        return self._clip

    def start(self) -> None:
        if self._thread is not None:
            return
        self._loop = asyncio.get_running_loop()
        self._load_model()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="inference", daemon=True)
        self._thread.start()
        self._sweep_thread = threading.Thread(target=self._sweep_loop, name="episode-sweep", daemon=True)
        self._sweep_thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
        if self._sweep_thread is not None:
            self._sweep_thread.join(timeout=3.0)
            self._sweep_thread = None

    def set_camera_configs(self, configs: dict[int, CameraConfig]) -> None:
        self._camera_configs = dict(configs)
        from app.db import get_conn
        import json as _json
        rows = get_conn().execute("SELECT id, classes_json, hysteresis_s FROM cameras").fetchall()
        self._camera_classes = {r["id"]: set(_json.loads(r["classes_json"])) for r in rows}
        self._camera_hysteresis = {r["id"]: r["hysteresis_s"] for r in rows}
        self._zone_cache.clear()
        self._zone_cache_ts.clear()

    def latest_detections(self, camera_id: int, max_age_s: float = 2.0) -> list[Detection]:
        with self._detections_lock:
            ts = self._latest_detections_ts.get(camera_id, 0.0)
            if time.time() - ts > max_age_s:
                return []
            return list(self._latest_detections.get(camera_id, []))

    def latest_state(self, zone_id: int) -> Optional[tuple[str, float, list]]:
        with self._state_lock:
            return self._state_latest.get(zone_id)

    def _zones_for(self, camera_id: int) -> list:
        now = time.time()
        if now - self._zone_cache_ts.get(camera_id, 0.0) > 5.0:
            self._zone_cache[camera_id] = load_zones(camera_id)
            self._zone_cache_ts[camera_id] = now
        return self._zone_cache[camera_id]

    def _class_ids_for(self, allowed_names: set[str]) -> list[int]:
        if not allowed_names:
            return []
        return [i for i, name in self._model_class_names.items() if name in allowed_names]

    def _run(self) -> None:
        while not self._stop.is_set():
            frame = self.bus.take(timeout=0.5)
            if frame is None:
                continue
            try:
                self._process_detection(frame)
                self._process_state(frame)
            except Exception:
                logger.exception("inference error on camera %d", frame.camera_id)

    def _process_detection(self, frame: Frame) -> None:
        camera_id = frame.camera_id
        allowed = self._camera_classes.get(camera_id, set())
        if not allowed:
            return
        class_ids = self._class_ids_for(allowed)
        if not class_ids:
            return

        h, w = frame.bgr.shape[:2]
        results = self._model.predict(
            frame.bgr,
            classes=class_ids,
            device=self.device,
            verbose=False,
            imgsz=640,
        )
        if not results:
            return
        r = results[0]
        all_zones = self._zones_for(camera_id)
        detection_zones = [z for z in all_zones if z.zone_type == "detection"]

        detections: list[Detection] = []
        events: list = []
        boxes = r.boxes
        if boxes is None or len(boxes) == 0:
            with self._detections_lock:
                self._latest_detections[camera_id] = []
                self._latest_detections_ts[camera_id] = time.time()
            return

        xyxy = boxes.xyxy.cpu().numpy() if hasattr(boxes.xyxy, "cpu") else boxes.xyxy
        confs = boxes.conf.cpu().numpy() if hasattr(boxes.conf, "cpu") else boxes.conf
        cls_ids = boxes.cls.cpu().numpy().astype(int) if hasattr(boxes.cls, "cpu") else boxes.cls

        for box, conf, cid in zip(xyxy, confs, cls_ids):
            name = self._model_class_names.get(int(cid), str(int(cid)))
            if name not in allowed:
                continue
            x1, y1, x2, y2 = float(box[0]), float(box[1]), float(box[2]), float(box[3])
            zone_id = match_zone((x1, y1, x2, y2), w, h, detection_zones)
            if detection_zones and zone_id is None:
                detections.append(Detection(
                    class_name=name, confidence=float(conf),
                    bbox_xyxy=(int(x1), int(y1), int(x2), int(y2)), zone_id=None,
                ))
                continue

            detections.append(Detection(
                class_name=name, confidence=float(conf),
                bbox_xyxy=(int(x1), int(y1), int(x2), int(y2)), zone_id=zone_id,
            ))

            frame_copy = copy.copy(frame.bgr)
            def _saver(episode_id: int, _bgr=frame_copy):
                return self.snapshot_store.save(episode_id, _bgr)

            event, _ = self.aggregator.observe(
                camera_id=camera_id, class_name=name, zone_id=zone_id,
                confidence=float(conf), ts=frame.ts, snapshot_saver=_saver,
            )
            if event is not None:
                events.append(event)

        with self._detections_lock:
            self._latest_detections[camera_id] = detections
            self._latest_detections_ts[camera_id] = time.time()

        for ev in events:
            self._publish(ev)

    def _process_state(self, frame: Frame) -> None:
        """Run CLIP classification on state zones for this camera's frame."""
        all_zones = self._zones_for(frame.camera_id)
        state_zones = [z for z in all_zones if z.zone_type == "state" and z.state_labels]
        if not state_zones:
            return

        now = time.time()
        clip = self._ensure_clip()

        for zone in state_zones:
            if now - self._state_last_ts.get(zone.zone_id, 0.0) < _STATE_CHECK_INTERVAL:
                continue

            roi = crop_zone(frame.bgr, zone.polygon)
            if roi is None or roi.size == 0:
                continue

            try:
                label, prob, ranked = clip.classify(roi, zone.state_labels)
            except Exception:
                logger.exception("CLIP classify failed zone %d", zone.zone_id)
                continue

            self._state_last_ts[zone.zone_id] = now

            with self._state_lock:
                self._state_latest[zone.zone_id] = (label, prob, ranked)

            prev_label = self._state_last_label.get(zone.zone_id)
            if label == prev_label:
                continue

            self._state_last_label[zone.zone_id] = label
            logger.info("state zone %d (%s): %s → %s (%.0f%%)",
                        zone.zone_id, zone.name, prev_label or "?", label, prob * 100)

            frame_copy = copy.copy(frame.bgr)
            def _saver(ep_id: int, _bgr=frame_copy):
                return self.snapshot_store.save(ep_id, _bgr)

            event, _ = self.aggregator.observe(
                camera_id=frame.camera_id,
                class_name=f"state:{label}",
                zone_id=zone.zone_id,
                confidence=prob,
                ts=now,
                snapshot_saver=_saver,
            )
            if event is not None:
                self._publish(event)

    def _sweep_loop(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(1.0)
            if self._stop.is_set():
                break
            try:
                events = self.aggregator.sweep(
                    time.time(),
                    lambda cid: self._camera_hysteresis.get(cid, 5.0),
                )
                for ev in events:
                    self._publish(ev)
            except Exception:
                logger.exception("sweep error")

    def _publish(self, event) -> None:
        if self._loop is None:
            return
        for pub in self.publishers:
            try:
                fut = asyncio.run_coroutine_threadsafe(pub.publish(event), self._loop)
                fut.add_done_callback(self._on_publish_done)
            except Exception:
                logger.exception("publisher submit failed: %s", pub)

    @staticmethod
    def _on_publish_done(fut: asyncio.Future) -> None:
        try:
            fut.result()
        except Exception:
            logger.exception("publisher raised")
