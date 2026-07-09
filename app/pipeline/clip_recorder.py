"""Event-triggered clip recorder.

Maintains a per-camera 1fps JPEG pre-buffer in memory. On a detection ENTER
event, flushes the pre-buffer into an MP4 and continues recording for
clip_post_s more seconds, then writes the file and logs it to the DB.

Only detection events trigger clips. State zone events are ignored.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from app.events.publisher import EpisodeEvent, EventPublisher
from app.settings import settings

logger = logging.getLogger("snvr.clips")


@dataclass
class _ActiveClip:
    episode_id: int
    camera_id: int
    zone_id: Optional[int]
    class_name: str
    started_at: float
    deadline: float                                  # wall-clock time to stop collecting
    frames: list = field(default_factory=list)       # list of (ts, jpeg_bytes)
    lock: threading.Lock = field(default_factory=threading.Lock)


class ClipRecorder(EventPublisher):
    def __init__(self) -> None:
        clips_dir = settings.clips_dir
        clips_dir.mkdir(parents=True, exist_ok=True)
        self._clips_dir = clips_dir
        self._pre_s = settings.clip_pre_s
        self._post_s = settings.clip_post_s
        self._max_age_days = settings.clip_max_age_days
        # Per-camera rolling 1fps pre-buffer (JPEG-compressed to save memory)
        self._pre_buffer: dict[int, deque] = {}
        self._last_push_ts: dict[int, float] = {}
        # Per-camera active clip (at most one per camera)
        self._active: dict[int, _ActiveClip] = {}
        self._active_lock = threading.Lock()
        # Background cleanup thread (daemon — stops with process)
        threading.Thread(target=self._cleanup_loop, daemon=True, name="clip-cleanup").start()

    # ── frame feed (called from InferenceWorker at inference rate) ────────────

    def extend_if_active(self, camera_id: int) -> None:
        """Extend the active clip deadline while detections are still present."""
        with self._active_lock:
            ac = self._active.get(camera_id)
        if ac is not None:
            new_deadline = time.time() + self._post_s
            with ac.lock:
                if new_deadline > ac.deadline:
                    ac.deadline = new_deadline

    def push_frame(self, camera_id: int, bgr: np.ndarray, ts: float) -> None:
        # Throttle to ~1fps
        if ts - self._last_push_ts.get(camera_id, 0.0) < 0.9:
            return
        self._last_push_ts[camera_id] = ts

        _, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 60])
        jpeg = buf.tobytes()

        # Update pre-buffer
        if camera_id not in self._pre_buffer:
            self._pre_buffer[camera_id] = deque(maxlen=self._pre_s)
        self._pre_buffer[camera_id].append((ts, jpeg))

        # Feed active clip if any
        with self._active_lock:
            ac = self._active.get(camera_id)
        if ac is not None:
            with ac.lock:
                if ts <= ac.deadline:
                    ac.frames.append((ts, jpeg))
                else:
                    # Deadline passed — finalise if we're the first to notice
                    with self._active_lock:
                        if self._active.get(camera_id) is ac:
                            del self._active[camera_id]
                    self._finalise(ac)

    # ── EventPublisher interface ───────────────────────────────────────────────

    async def publish(self, event: EpisodeEvent) -> None:
        # Only detection ENTER events (state zone events are excluded)
        if event.kind != "ENTER" or event.class_name.startswith("state:"):
            return
        # Respect per-zone clip_enabled flag
        if event.zone_id is not None:
            from app.db import get_conn
            row = get_conn().execute(
                "SELECT clip_enabled FROM zones WHERE id = ?", (event.zone_id,)
            ).fetchone()
            if row is not None and not row["clip_enabled"]:
                return

        with self._active_lock:
            existing = self._active.get(event.camera_id)
            if existing is not None:
                # Extend deadline on subsequent detections for same camera
                with existing.lock:
                    existing.deadline = time.time() + self._post_s
                logger.debug("clip extended for camera %d (episode %d)", event.camera_id, event.episode_id)
                return

            # Snapshot current pre-buffer
            pre = list(self._pre_buffer.get(event.camera_id, []))
            ac = _ActiveClip(
                episode_id=event.episode_id,
                camera_id=event.camera_id,
                zone_id=event.zone_id,
                class_name=event.class_name,
                started_at=time.time(),
                deadline=time.time() + self._post_s,
                frames=list(pre),
            )
            self._active[event.camera_id] = ac

        logger.info("clip started for camera %d episode %d (%s)", event.camera_id, event.episode_id, event.class_name)
        # Start a watchdog thread that finalises the clip once the deadline passes
        threading.Thread(target=self._watchdog, args=(ac,), daemon=True, name=f"clip-{event.camera_id}").start()

    # ── internal ──────────────────────────────────────────────────────────────

    def _watchdog(self, ac: _ActiveClip) -> None:
        """Wait until deadline + a small grace period, then finalise."""
        while True:
            with ac.lock:
                deadline = ac.deadline
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            time.sleep(min(remaining + 0.5, 2.0))

        # Remove from active dict (if not already removed by push_frame)
        with self._active_lock:
            if self._active.get(ac.camera_id) is ac:
                del self._active[ac.camera_id]

        self._finalise(ac)

    def _finalise(self, ac: _ActiveClip) -> None:
        with ac.lock:
            frames = list(ac.frames)
        if not frames:
            logger.warning("clip for camera %d has no frames, skipping", ac.camera_id)
            return

        ts_str = time.strftime("%Y%m%d_%H%M%S", time.localtime(ac.started_at))
        filename = f"cam{ac.camera_id}_ep{ac.episode_id}_{ts_str}.mp4"
        out_path = self._clips_dir / filename

        try:
            self._write_video(frames, out_path)
        except Exception:
            logger.exception("failed to write clip %s", out_path)
            return

        duration_s = frames[-1][0] - frames[0][0] if len(frames) > 1 else 0.0
        self._save_to_db(ac, out_path, len(frames), duration_s)
        logger.info("clip saved: %s (%d frames, %.0fs)", out_path.name, len(frames), duration_s)

    def _write_video(self, frames: list, out_path: Path) -> None:
        if shutil.which("ffmpeg"):
            self._write_ffmpeg(frames, out_path)
        else:
            self._write_cv2(frames, out_path)

    def _write_ffmpeg(self, frames: list, out_path: Path) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for i, (_, jpeg) in enumerate(frames):
                (tmp_path / f"frame_{i:06d}.jpg").write_bytes(jpeg)
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-r", "1",
                    "-i", str(tmp_path / "frame_%06d.jpg"),
                    "-vcodec", "libx264", "-crf", "23", "-preset", "fast",
                    "-movflags", "+faststart",
                    str(out_path),
                ],
                check=True,
                capture_output=True,
            )

    def _write_cv2(self, frames: list, out_path: Path) -> None:
        first_bgr = cv2.imdecode(np.frombuffer(frames[0][1], np.uint8), cv2.IMREAD_COLOR)
        if first_bgr is None:
            raise RuntimeError("could not decode first frame")
        h, w = first_bgr.shape[:2]
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        out = cv2.VideoWriter(str(out_path), fourcc, 1.0, (w, h))
        try:
            for _, jpeg in frames:
                bgr = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
                if bgr is not None:
                    out.write(bgr)
        finally:
            out.release()

    def _cleanup_loop(self) -> None:
        """Run cleanup once at startup then every 6 hours."""
        while True:
            try:
                self.cleanup_old()
            except Exception:
                logger.exception("clip cleanup error")
            time.sleep(6 * 3600)

    def cleanup_old(self) -> int:
        """Delete clips older than clip_max_age_days. Returns number of clips removed."""
        if self._max_age_days <= 0:
            return 0
        from app.db import get_conn, tx
        cutoff = time.time() - self._max_age_days * 86400
        rows = get_conn().execute(
            "SELECT id, path FROM clips WHERE created_at < ?", (cutoff,)
        ).fetchall()
        if not rows:
            return 0
        count = 0
        for r in rows:
            try:
                os.remove(r["path"])
            except OSError:
                pass
            with tx() as conn:
                conn.execute("DELETE FROM clips WHERE id = ?", (r["id"],))
            count += 1
        logger.info("clip cleanup: removed %d clips older than %d days", count, self._max_age_days)
        return count

    def _save_to_db(self, ac: _ActiveClip, path: Path, frame_count: int, duration_s: float) -> None:
        from app.db import get_conn, tx
        try:
            with tx() as conn:
                conn.execute(
                    """
                    INSERT INTO clips (episode_id, camera_id, zone_id, class_name,
                                       path, duration_s, frame_count, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (ac.episode_id, ac.camera_id, ac.zone_id, ac.class_name,
                     str(path), round(duration_s, 1), frame_count, ac.started_at),
                )
        except Exception:
            logger.exception("failed to save clip to DB")
