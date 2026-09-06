"""ffmpeg-subprocess capture worker: offloads RTSP decode to dedicated hardware.

The OpenCV path (`capture.CaptureWorker`) links FFmpeg as a library and decodes
every frame in-process, in software, on the Python thread. With several 1080p
cameras that saturates the CPU while a GPU's decode block (NVDEC / VAAPI / QSV)
sits idle.

This worker spawns one `ffmpeg` per camera instead, so:
  - decode runs on the accelerator named by SNVR_CAPTURE_HWACCEL,
  - the `fps` filter drops frames *before* they cross into Python, so we no
    longer decode 25fps only to discard 80% of it at the target_fps gate,
  - decode lives in a separate process, off the GIL.

Frames arrive as raw BGR24 on stdout, which is what the rest of the pipeline
(and Ultralytics) already expects.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time
from functools import lru_cache
from typing import Optional

import numpy as np

from app.pipeline.capture import CameraConfig
from app.pipeline.frame_bus import Frame, FrameBus
from app.settings import settings

logger = logging.getLogger("snvr.capture.ffmpeg")


@lru_cache(maxsize=1)
def _rtsp_timeout_flag() -> str:
    """Socket-timeout option name for the rtsp demuxer.

    Order matters: ffmpeg 4.x exposes BOTH options, and there `-timeout` means
    "seconds to wait for an INCOMING connection" and implies listen mode — using
    it makes ffprobe sit waiting to be dialled instead of dialling the camera,
    so every probe times out and looks like an unreachable camera. `-stimeout`
    is the socket I/O timeout we actually want. ffmpeg >=5 dropped `-stimeout`
    and redefined `-timeout` to mean socket I/O, so prefer -stimeout whenever
    it exists and only fall back to -timeout when it does not.
    """
    try:
        out = subprocess.run(
            ["ffmpeg", "-hide_banner", "-h", "demuxer=rtsp"],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except Exception:
        return "-stimeout"
    return "-stimeout" if "-stimeout" in out else "-timeout"


@lru_cache(maxsize=1)
def _available_hwaccels() -> frozenset[str]:
    try:
        out = subprocess.run(
            ["ffmpeg", "-hide_banner", "-hwaccels"],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except Exception:
        return frozenset()
    # Output is a "Hardware acceleration methods:" header then one per line
    return frozenset(l.strip() for l in out.splitlines()[1:] if l.strip())


@lru_cache(maxsize=1)
def _has_nvcuvid() -> Optional[bool]:
    """Is libnvcuvid actually loadable here? None when we can't tell.

    `ffmpeg -hwaccels` reports what the binary was COMPILED with, not what is
    usable at runtime — a stock ffmpeg lists `cuda` even in a container that has
    no NVDEC access at all. The real gate is libnvcuvid, which the NVIDIA
    container runtime only injects when asked for the 'video' driver capability.
    """
    try:
        out = subprocess.run(
            ["ldconfig", "-p"], capture_output=True, text=True, timeout=10
        ).stdout
    except Exception:
        return None  # no glibc ldconfig (macOS/Windows) — don't block on it
    return "libnvcuvid" in out


def preflight(hwaccel: str) -> tuple[bool, str]:
    """Check ffmpeg exists and can really use `hwaccel`. Returns (ok, message)."""
    if not shutil.which("ffmpeg"):
        return False, "ffmpeg not found on PATH"
    if not shutil.which("ffprobe"):
        return False, "ffprobe not found on PATH"
    if not hwaccel:
        return True, "ffmpeg capture, software decode (no hwaccel configured)"

    avail = _available_hwaccels()
    if hwaccel not in avail:
        return False, (
            f"hwaccel '{hwaccel}' not compiled into ffmpeg; it reports "
            f"{sorted(avail) or 'none'}"
        )

    # Compiled-in is necessary but not sufficient — check the runtime library.
    if hwaccel == "cuda" and _has_nvcuvid() is False:
        return False, (
            "ffmpeg lists 'cuda' but libnvcuvid is not present, so NVDEC will "
            "fail at decode time. Set NVIDIA_DRIVER_CAPABILITIES=compute,utility,video "
            "on the container (compute,utility alone does not expose it) and recreate it."
        )
    return True, f"ffmpeg capture, {hwaccel} hardware decode"


class FFmpegCaptureWorker:
    """Drop-in replacement for CaptureWorker backed by an ffmpeg subprocess."""

    _RECONNECT_BASE_S = 1.0
    _RECONNECT_MAX_S = 30.0

    def __init__(self, cfg: CameraConfig, bus: FrameBus) -> None:
        self.cfg = cfg
        self.bus = bus
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._proc: Optional[subprocess.Popen] = None
        self._proc_lock = threading.Lock()
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
            target=self._run, name=f"cap-ff-{self.cfg.camera_id}", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        self._kill_proc()          # unblocks the thread's blocking read on stdout
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def update_config(self, cfg: CameraConfig) -> None:
        # target_fps is baked into the ffmpeg filter graph, so unlike the OpenCV
        # worker a change to it also requires a restart.
        needs_restart = (
            cfg.rtsp_url != self.cfg.rtsp_url
            or cfg.enabled != self.cfg.enabled
            or cfg.target_fps != self.cfg.target_fps
        )
        self.cfg = cfg
        if needs_restart:
            self.stop()
            if cfg.enabled:
                self.start()

    # ── internals ─────────────────────────────────────────────────────────────

    def _output_fps(self) -> float:
        """Frames per second to pull from ffmpeg.

        target_fps == 0 means "no inference, preview only", so fall back to the
        preview rate rather than streaming full rate for nothing.
        """
        return self.cfg.target_fps if self.cfg.target_fps > 0 else settings.preview_fps

    def _probe_size(self) -> Optional[tuple[int, int]]:
        """Native WxH of the video stream — needed to size raw frame reads."""
        cmd = [
            "ffprobe", "-hide_banner", "-loglevel", "error",
            "-rtsp_transport", "tcp",
            _rtsp_timeout_flag(), "5000000",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0:s=x",
            self.cfg.rtsp_url,
        ]
        try:
            out = subprocess.run(
                cmd, capture_output=True, text=True, timeout=20
            ).stdout.strip()
            w_s, _, h_s = out.partition("x")
            w, h = int(w_s), int(h_s)
            if w <= 0 or h <= 0:
                return None
            return w, h
        except Exception:
            return None

    def _build_cmd(self, out_w: int, out_h: int) -> list[str]:
        hw = settings.capture_hwaccel
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin"]
        # Input options must precede -i
        cmd += ["-rtsp_transport", "tcp", _rtsp_timeout_flag(), "5000000"]
        cmd += ["-fflags", "nobuffer"]
        if hw:
            # Plain -hwaccel (rather than -c:v h264_cuvid) so the same command
            # works for H.264 and HEVC cameras. Frames land back in system
            # memory, which is where Ultralytics needs them anyway.
            cmd += ["-hwaccel", hw]
        cmd += ["-i", self.cfg.rtsp_url]
        cmd += ["-an", "-sn"]

        vf = [f"fps={self._output_fps():g}"]
        if settings.capture_width and out_w != settings.capture_width:
            vf.append(f"scale={settings.capture_width}:-2")
        cmd += ["-vf", ",".join(vf)]

        cmd += ["-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
        return cmd

    def _kill_proc(self) -> None:
        with self._proc_lock:
            proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except Exception:
            pass

    def _drain_stderr(self, proc: subprocess.Popen) -> None:
        """Consume stderr so a full pipe can never block ffmpeg."""
        if proc.stderr is None:
            return
        for raw in iter(proc.stderr.readline, b""):
            line = raw.decode("utf-8", "replace").strip()
            if line:
                self._last_error = line
                logger.warning("camera %s ffmpeg: %s", self.cfg.name, line)

    @staticmethod
    def _read_exact(pipe, n: int) -> Optional[bytearray]:
        """Read exactly n bytes; pipes routinely return short reads."""
        buf = bytearray(n)
        view = memoryview(buf)
        got = 0
        while got < n:
            k = pipe.readinto(view[got:])
            if not k:
                return None
            got += k
        return buf

    def _run(self) -> None:
        backoff = self._RECONNECT_BASE_S
        while not self._stop.is_set():
            if not self.cfg.enabled:
                self._status = "disabled"
                self._stop.wait(1.0)
                continue

            size = self._probe_size()
            if size is None:
                self._status = "disconnected"
                self._last_error = "ffprobe failed (stream unreachable?)"
                logger.warning(
                    "camera %s: probe failed, retry in %.1fs", self.cfg.name, backoff
                )
                self._stop.wait(backoff)
                backoff = min(backoff * 2, self._RECONNECT_MAX_S)
                continue

            native_w, native_h = size
            if settings.capture_width and settings.capture_width < native_w:
                out_w = settings.capture_width
                # scale=W:-2 keeps aspect and forces an even height
                out_h = int(round(native_h * out_w / native_w / 2)) * 2
            else:
                out_w, out_h = native_w, native_h

            cmd = self._build_cmd(native_w, native_h)
            logger.info(
                "camera %s: starting ffmpeg %dx%d @%.3gfps hwaccel=%s",
                self.cfg.name, out_w, out_h, self._output_fps(),
                settings.capture_hwaccel or "none",
            )

            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    bufsize=0,
                )
            except Exception as e:
                self._status = "disconnected"
                self._last_error = f"ffmpeg spawn failed: {e}"
                logger.exception("camera %s: ffmpeg spawn failed", self.cfg.name)
                self._stop.wait(backoff)
                backoff = min(backoff * 2, self._RECONNECT_MAX_S)
                continue

            with self._proc_lock:
                self._proc = proc
            threading.Thread(
                target=self._drain_stderr, args=(proc,), daemon=True,
                name=f"cap-ff-err-{self.cfg.camera_id}",
            ).start()

            self._status = "connected"
            self._last_error = None
            backoff = self._RECONNECT_BASE_S
            logger.info("camera %s: connected", self.cfg.name)

            frame_bytes = out_w * out_h * 3
            for_inference = self.cfg.target_fps > 0
            try:
                while not self._stop.is_set():
                    buf = self._read_exact(proc.stdout, frame_bytes)
                    if buf is None:
                        self._status = "disconnected"
                        logger.warning(
                            "camera %s: ffmpeg stream ended, reconnecting", self.cfg.name
                        )
                        break
                    bgr = np.frombuffer(buf, np.uint8).reshape(out_h, out_w, 3)
                    now = time.time()
                    self._last_frame_ts = now
                    # ffmpeg already rate-limited us, so every frame is a keeper
                    self.bus.submit(
                        Frame(self.cfg.camera_id, now, bgr), for_inference
                    )
            finally:
                self._kill_proc()

            if not self._stop.is_set():
                self._stop.wait(backoff)
                backoff = min(backoff * 2, self._RECONNECT_MAX_S)
