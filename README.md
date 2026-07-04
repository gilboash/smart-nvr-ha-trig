# smart-nvr-ha-trig

Lightweight YOLO inference on RTSP cameras, running alongside Frigate on a home NVR. Detects objects per camera using configurable zones, class filters, and FPS — and emits HA-friendly episode events (ENTER / EXIT with hysteresis).

Phase 1: RTSP → YOLO → zones → episodes → SQLite + web UI.
Phase 2 (planned): forward events to Home Assistant via MQTT or webhook.

---

## Running the app

### Option 1 — Docker on Windows (recommended for production)

Requires: Docker Desktop with WSL2 backend, recent NVIDIA driver.

```powershell
# Clone and enter the repo
git clone https://github.com/gilboash/smart-nvr-ha-trig.git
cd smart-nvr-ha-trig

# Build and start
docker compose up -d --build

# View logs
docker compose logs -f

# Stop
docker compose down

# Update after a git pull
git pull
docker compose up -d --build
```

Open `http://localhost:7070` (or `http://<windows-ip>:7070` from another machine on the LAN).

> **GPU note**: the compose file reserves 1 NVIDIA GPU. Requires Docker Desktop WSL2 backend + `nvidia-container-toolkit` inside the WSL2 distro. Windows 11 or Windows 10 21H2+ required for WSL2 GPU passthrough.

---

### Option 2 — Native Python on Mac or Linux (dev / testing)

Requires: Python 3.11+. Runs on CPU (or MPS on Apple Silicon).

```bash
git clone https://github.com/gilboash/smart-nvr-ha-trig.git
cd smart-nvr-ha-trig

python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env   # defaults are fine for local dev

./scripts/dev_run.sh
```

Open `http://localhost:7070`.

> **Apple Silicon tip**: set `SNVR_DEVICE=mps` in `.env` for faster inference using Apple's GPU.

---

### Option 3 — Native Python on Windows (SSH / testing, no Docker)

Requires: Python 3.11+ installed on the Windows machine.

```powershell
git clone https://github.com/gilboash/smart-nvr-ha-trig.git
cd smart-nvr-ha-trig

python -m venv .venv
.\.venv\Scripts\activate
pip install --upgrade pip
pip install -e ".[dev]"

copy .env.example .env

python -m uvicorn app.main:app --host 0.0.0.0 --port 7070 --reload
```

Open `http://<windows-ip>:7070` from any browser on the LAN. Run `ipconfig` to find the Windows machine's IP.

---

## Configuration

All config lives in SQLite (`data/snvr.db`) and is managed via the web UI. Environment variables (in `.env` or Docker env) control startup behaviour:

| Variable | Default | Description |
|---|---|---|
| `SNVR_PORT` | `7070` | Listening port |
| `SNVR_DB_PATH` | `./data/snvr.db` | SQLite database path |
| `SNVR_SNAPSHOT_DIR` | `./data/snapshots` | Where episode snapshots are saved |
| `SNVR_MODEL_DIR` | `./config/models` | Where YOLO `.pt` weights are stored |
| `SNVR_DEVICE` | `auto` | Inference device: `auto`, `cuda`, `cuda:0`, `mps`, `cpu` |
| `SNVR_LOG_LEVEL` | `INFO` | Logging level |

Model weights (`yolov8n.pt`) are auto-downloaded by Ultralytics on first inference run if not already present in `SNVR_MODEL_DIR`.

---

## Notes

- **Concurrent RTSP sessions**: cheap cameras cap at 1–2 concurrent sessions. If Frigate already holds the main stream, point this at the sub-stream — or switch Frigate to use go2rtc restream so multiple readers can connect.
- **LAN only**: no authentication in Phase 1. Put behind Caddy or nginx with basic auth before exposing beyond your LAN.
- **Runs alongside Frigate**: reads RTSP independently. No exclusive lock — but watch your camera's session limit (above).
