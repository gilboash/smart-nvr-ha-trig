"""Always-on 1fps DVR recorder — flushes 5-minute H.264 MP4 segments continuously."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from app.settings import settings

logger = logging.getLogger("snvr.recorder")


class ContinuousRecorder:
    def __init__(self) -> None:
        self._dir = settings.recordings_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._segment_s = settings.recording_segment_min * 60
        self._max_age_days = settings.recording_max_age_days

        self._lock = threading.Lock()
        self._frames: dict[int, list] = {}              # camera_id → [(ts, jpeg_bytes)]
        self._segment_start: dict[int, float] = {}      # camera_id → segment start ts
        self._segment_db_id: dict[int, Optional[int]] = {}  # camera_id → open recordings row id
        self._last_push_ts: dict[int, float] = {}       # 1fps throttle
        self._record_enabled: dict[int, bool] = {}      # lazily cached from DB

        threading.Thread(target=self._cleanup_loop, daemon=True, name="rec-cleanup").start()

    # ── Public ────────────────────────────────────────────────────────────────

    def push_frame(self, camera_id: int, bgr: np.ndarray, ts: float) -> None:
        if not self._is_record_enabled(camera_id):
            return
        if ts - self._last_push_ts.get(camera_id, 0.0) < 0.9:
            return
        self._last_push_ts[camera_id] = ts

        _, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 60])
        jpeg = buf.tobytes()

        flush_args: Optional[tuple] = None
        with self._lock:
            if camera_id not in self._segment_start:
                self._frames[camera_id] = []
                self._segment_start[camera_id] = ts
                self._open_segment(camera_id, ts)

            self._frames[camera_id].append((ts, jpeg))

            age = ts - self._segment_start[camera_id]
            if age >= self._segment_s:
                frames = self._frames.pop(camera_id)
                seg_id = self._segment_db_id.pop(camera_id, None)
                seg_start = self._segment_start.pop(camera_id)
                self._frames[camera_id] = []
                self._segment_start[camera_id] = ts
                self._open_segment(camera_id, ts)
                flush_args = (camera_id, frames, seg_id, seg_start, ts)

        if flush_args is not None:
            threading.Thread(
                target=self._flush, args=flush_args, daemon=True,
                name=f"rec-flush-{camera_id}"
            ).start()

    def invalidate_record_cache(self, camera_id: Optional[int] = None) -> None:
        with self._lock:
            if camera_id is None:
                self._record_enabled.clear()
            else:
                self._record_enabled.pop(camera_id, None)

    def cleanup_old(self) -> int:
        if self._max_age_days <= 0:
            return 0
        from app.db import get_conn, tx
        cutoff = time.time() - self._max_age_days * 86400
        rows = get_conn().execute(
            "SELECT id, path FROM recordings WHERE start_ts < ? AND end_ts IS NOT NULL",
            (cutoff,),
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
                conn.execute("DELETE FROM recordings WHERE id = ?", (r["id"],))
            count += 1
        logger.info("recording cleanup: removed %d segments older than %d days", count, self._max_age_days)
        return count

    # ── Internal ──────────────────────────────────────────────────────────────

    def _is_record_enabled(self, camera_id: int) -> bool:
        with self._lock:
            if camera_id in self._record_enabled:
                return self._record_enabled[camera_id]
        from app.db import get_conn
        row = get_conn().execute(
            "SELECT record_enabled FROM cameras WHERE id = ?", (camera_id,)
        ).fetchone()
        result = bool(row["record_enabled"]) if row else False
        with self._lock:
            self._record_enabled[camera_id] = result
        return result

    def _open_segment(self, camera_id: int, ts: float) -> None:
        """Insert a new DB row for the in-progress segment. Called while holding self._lock."""
        ts_str = time.strftime("%Y%m%d_%H%M%S", time.localtime(ts))
        filename = f"cam{camera_id}_{ts_str}.mp4"
        path = str(self._dir / filename)
        from app.db import tx
        try:
            with tx() as conn:
                cur = conn.execute(
                    "INSERT INTO recordings (camera_id, start_ts, end_ts, path, frame_count) "
                    "VALUES (?, ?, NULL, ?, 0)",
                    (camera_id, ts, path),
                )
                self._segment_db_id[camera_id] = cur.lastrowid
        except Exception:
            logger.exception("failed to open segment for camera %d", camera_id)
            self._segment_db_id[camera_id] = None

    def _flush(
        self, camera_id: int, frames: list, seg_id: Optional[int],
        seg_start: float, end_ts: float
    ) -> None:
        if not frames:
            return
        ts_str = time.strftime("%Y%m%d_%H%M%S", time.localtime(seg_start))
        filename = f"cam{camera_id}_{ts_str}.mp4"
        out_path = self._dir / filename

        try:
            self._write_video(frames, out_path)
        except Exception:
            logger.exception("failed to write recording %s", out_path)
            return

        if seg_id is not None:
            from app.db import tx
            try:
                with tx() as conn:
                    conn.execute(
                        "UPDATE recordings SET end_ts = ?, frame_count = ? WHERE id = ?",
                        (end_ts, len(frames), seg_id),
                    )
            except Exception:
                logger.exception("failed to update recordings row %d", seg_id)

        logger.info("recording segment saved: %s (%d frames)", filename, len(frames))

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
            encode_timeout = max(60, len(frames) * 2)
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-r", "1",
                    "-i", str(tmp_path / "frame_%06d.jpg"),
                    "-vcodec", "libx264", "-crf", "28", "-preset", "fast",
                    "-movflags", "+faststart",
                    str(out_path),
                ],
                check=True,
                capture_output=True,
                timeout=encode_timeout,
            )

    def _write_cv2(self, frames: list, out_path: Path) -> None:
        first = cv2.imdecode(np.frombuffer(frames[0][1], np.uint8), cv2.IMREAD_COLOR)
        if first is None:
            raise RuntimeError("could not decode first frame")
        h, w = first.shape[:2]
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
        while True:
            try:
                self.cleanup_old()
            except Exception:
                logger.exception("recording cleanup error")
            time.sleep(6 * 3600)
