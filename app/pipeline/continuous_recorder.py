"""Always-on DVR recorder — streams frames to disk as they arrive, flushes to H.264 MP4."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from app.settings import settings

logger = logging.getLogger("snvr.recorder")

# Global semaphore — limits concurrent ffmpeg encodes to avoid RAM spikes
# when many cameras flush segments at the same time.
_encode_sem = threading.Semaphore(2)


class ContinuousRecorder:
    def __init__(self) -> None:
        self._dir = settings.recordings_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._segment_s = settings.recording_segment_min * 60
        self._max_age_days = settings.recording_max_age_days

        self._lock = threading.Lock()
        # Per-camera in-progress segment state — no frame list; frames go straight to disk
        self._tmp_dir: dict[int, Path] = {}              # camera_id → staging dir
        self._frame_idx: dict[int, int] = {}             # camera_id → next frame number
        self._segment_start: dict[int, float] = {}       # camera_id → segment start ts
        self._segment_db_id: dict[int, Optional[int]] = {}
        self._last_push_ts: dict[int, float] = {}
        self._record_enabled: dict[int, bool] = {}
        self._record_fps: dict[int, float] = {}

        threading.Thread(target=self._cleanup_loop, daemon=True, name="rec-cleanup").start()

    # ── Public ────────────────────────────────────────────────────────────────

    def push_frame(self, camera_id: int, bgr: np.ndarray, ts: float) -> None:
        if not self._is_record_enabled(camera_id):
            return
        min_gap = 1.0 / self._get_record_fps(camera_id)
        if ts - self._last_push_ts.get(camera_id, 0.0) < min_gap * 0.9:
            return
        self._last_push_ts[camera_id] = ts

        ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 60])
        if not ok:
            return
        jpeg = buf.tobytes()

        flush_args: Optional[tuple] = None
        with self._lock:
            if camera_id not in self._segment_start:
                # Stagger first flush: spread cameras across the segment window
                # using camera_id mod segment_s so they never all flush together
                offset_s = (camera_id * (self._segment_s / 7)) % self._segment_s
                self._open_segment(camera_id, ts, offset_s=offset_s)

            # Write frame directly to disk — no in-memory accumulation
            idx = self._frame_idx[camera_id]
            frame_path = self._tmp_dir[camera_id] / f"frame_{idx:06d}.jpg"
            self._frame_idx[camera_id] = idx + 1

            age = ts - self._segment_start[camera_id]
            if age >= self._segment_s:
                tmp_dir = self._tmp_dir.pop(camera_id)
                frame_count = self._frame_idx.pop(camera_id)
                seg_id = self._segment_db_id.pop(camera_id, None)
                seg_start = self._segment_start.pop(camera_id)
                fps = self._record_fps.get(camera_id, 1.0)
                self._open_segment(camera_id, ts)
                flush_args = (camera_id, tmp_dir, frame_count, seg_id, seg_start, ts, fps)

        # Write outside the lock so encoding/IO doesn't block push_frame
        frame_path.write_bytes(jpeg)

        if flush_args is not None:
            threading.Thread(
                target=self._flush, args=flush_args, daemon=True,
                name=f"rec-flush-{camera_id}"
            ).start()

    def invalidate_record_cache(self, camera_id: Optional[int] = None) -> None:
        with self._lock:
            if camera_id is None:
                self._record_enabled.clear()
                self._record_fps.clear()
            else:
                self._record_enabled.pop(camera_id, None)
                self._record_fps.pop(camera_id, None)

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

    def _open_segment(self, camera_id: int, ts: float, offset_s: float = 0.0) -> None:
        """Create staging dir and DB row for a new in-progress segment. Caller holds lock."""
        ts_str = time.strftime("%Y%m%d_%H%M%S", time.localtime(ts))
        tmp_dir = self._dir / ".tmp" / f"cam{camera_id}_{ts_str}"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        self._tmp_dir[camera_id] = tmp_dir
        self._frame_idx[camera_id] = 0
        # offset_s backdates the segment start so cameras stagger their flush times
        self._segment_start[camera_id] = ts - offset_s

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
        self, camera_id: int, tmp_dir: Path, frame_count: int,
        seg_id: Optional[int], seg_start: float, end_ts: float, fps: float,
    ) -> None:
        if frame_count == 0:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return

        ts_str = time.strftime("%Y%m%d_%H%M%S", time.localtime(seg_start))
        out_path = self._dir / f"cam{camera_id}_{ts_str}.mp4"

        try:
            self._encode(tmp_dir, out_path, frame_count, fps)
        except Exception:
            logger.exception("failed to encode recording %s", out_path)
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return

        shutil.rmtree(tmp_dir, ignore_errors=True)

        if seg_id is not None:
            from app.db import tx
            try:
                with tx() as conn:
                    conn.execute(
                        "UPDATE recordings SET end_ts = ?, frame_count = ? WHERE id = ?",
                        (end_ts, frame_count, seg_id),
                    )
            except Exception:
                logger.exception("failed to update recordings row %d", seg_id)

        logger.info("recording segment saved: %s (%d frames)", out_path.name, frame_count)

    def _encode(self, tmp_dir: Path, out_path: Path, frame_count: int, fps: float) -> None:
        encode_timeout = max(60, frame_count * 2)
        with _encode_sem:  # at most 2 concurrent encodes regardless of camera count
            if shutil.which("ffmpeg"):
                subprocess.run(
                    [
                        "ffmpeg", "-y",
                        "-r", str(fps),
                        "-i", str(tmp_dir / "frame_%06d.jpg"),
                        "-vcodec", "libx264", "-crf", "28", "-preset", "fast",
                        "-movflags", "+faststart",
                        str(out_path),
                    ],
                    check=True,
                    capture_output=True,
                    timeout=encode_timeout,
                )
            else:
                # OpenCV fallback
                first = cv2.imdecode(
                    np.frombuffer((tmp_dir / "frame_000000.jpg").read_bytes(), np.uint8),
                    cv2.IMREAD_COLOR,
                )
                if first is None:
                    raise RuntimeError("could not decode first frame")
                h, w = first.shape[:2]
                fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                writer = cv2.VideoWriter(str(out_path), fourcc, fps, (w, h))
                try:
                    for i in range(frame_count):
                        data = (tmp_dir / f"frame_{i:06d}.jpg").read_bytes()
                        bgr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
                        if bgr is not None:
                            writer.write(bgr)
                finally:
                    writer.release()

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

    def _get_record_fps(self, camera_id: int) -> float:
        with self._lock:
            if camera_id in self._record_fps:
                return self._record_fps[camera_id]
        from app.db import get_conn
        row = get_conn().execute(
            "SELECT record_fps FROM cameras WHERE id = ?", (camera_id,)
        ).fetchone()
        result = float(row["record_fps"]) if row and row["record_fps"] else 1.0
        with self._lock:
            self._record_fps[camera_id] = result
        return result

    def _cleanup_loop(self) -> None:
        while True:
            try:
                self.cleanup_old()
            except Exception:
                logger.exception("recording cleanup error")
            try:
                from app.events.snapshot_store import SnapshotStore
                SnapshotStore().cleanup_old()
            except Exception:
                logger.exception("snapshot cleanup error")
            time.sleep(6 * 3600)
