# smart-nvr-ha-trig

Lightweight YOLO inference on RTSP cameras, running alongside Frigate on a Windows NVR. Emits HA-friendly episode events with per-camera FPS, class filters, and user-drawn zones.

Phase 1 scope: RTSP capture → YOLO inference (CUDA) → zone/class filter → episode aggregation → SQLite + WebSocket + local web UI. Phase 2 will forward events to Home Assistant (MQTT/webhook).

## Quick start (Windows + Docker Desktop + WSL2 + NVIDIA GPU)

```powershell
docker compose up -d --build
# open http://<windows-ip>:7070
```

Requirements:
- Windows 11 or Windows 10 21H2+
- Docker Desktop with WSL2 backend
- Recent NVIDIA driver on the host
- `nvidia-container-toolkit` inside the WSL2 distro

## Dev (macOS, CPU)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
./scripts/dev_run.sh
```

Ultralytics auto-falls back to CPU if CUDA is unavailable.

## Notes

- **Concurrent RTSP sessions**: cheap cameras cap at 1–2 sessions. If Frigate holds the main stream, point this at the sub-stream, or switch Frigate to publish via go2rtc restream so multiple readers work.
- **LAN only**: no auth in Phase 1. Put behind Caddy/nginx-basic-auth before exposing beyond LAN.
- **Config lives in SQLite** at `SNVR_DB_PATH`. Snapshots in `SNVR_SNAPSHOT_DIR`. Model weights in `SNVR_MODEL_DIR` (Ultralytics auto-downloads `yolov8n.pt` on first run).
