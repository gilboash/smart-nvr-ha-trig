# naco-real-smart-nvr

Lightweight NVR that runs YOLO object detection on RTSP cameras, classifies zone states with a few-shot visual classifier (no cloud), and pushes events to Home Assistant via MQTT Discovery — all from a self-hosted web UI.

**Key features**
- Per-camera detection zones with configurable classes, FPS, hysteresis, and confidence threshold
- State zones (open/closed, present/absent, etc.) trained with 3–5 example photos per label — no API key, fully local
- Home Assistant MQTT Discovery: cameras appear as HA devices, zones as `binary_sensor` / `sensor` entities automatically
- Web UI for camera management, zone drawing, training, live preview, and event history
- Settings page writes directly to `.env` — no rebuild needed for config changes

---

## Quick start

### Prerequisites

| | Mac | Windows |
|---|---|---|
| Docker | Docker Desktop for Mac | Docker Desktop (WSL2 backend) |
| GPU (optional) | Apple Silicon (MPS) | NVIDIA + nvidia-container-toolkit |
| Python (no Docker) | Python 3.11+ | Python 3.11+ |

---

## Option 1 — Docker on Windows (recommended for GPU / production)

Requires Docker Desktop with WSL2 backend and a recent NVIDIA driver.

```powershell
git clone https://github.com/gilboash/smart-nvr-ha-trig.git
cd smart-nvr-ha-trig

# Copy and edit config
copy .env.example .env
notepad .env

# Build and start
docker compose up -d --build

# View logs
docker compose logs -f

# Stop
docker compose down
```

Open `http://localhost:7070` — or `http://<windows-ip>:7070` from any device on the LAN.

**First login**: the admin password is auto-generated on first boot and printed in the logs:
```
docker compose logs | findstr "admin password"
```
Or set it in advance by adding `SNVR_ADMIN_PASSWORD=yourpassword` to `.env`.

**GPU note**: the compose file reserves 1 NVIDIA GPU via `nvidia-container-toolkit`. Requires Windows 11 or Windows 10 21H2+ for WSL2 GPU passthrough. To run on CPU only, remove the `deploy.resources` block from `docker-compose.yml` and set `SNVR_DEVICE=cpu` in `.env`.

**After a code update:**
```powershell
git pull
docker compose up -d --build
```

**After a `.env` change only** (no rebuild needed):
```powershell
docker compose up -d
```

---

## Option 2 — Docker on Mac

Runs on CPU or Apple Silicon MPS. No GPU reservation needed.

```bash
git clone https://github.com/gilboash/smart-nvr-ha-trig.git
cd smart-nvr-ha-trig

cp .env.example .env
# Optional: set SNVR_DEVICE=mps for Apple Silicon GPU acceleration

# Remove the GPU reservation from docker-compose.yml (Mac doesn't support it):
# Delete the entire `deploy:` block before running.

docker compose up -d --build
docker compose logs -f
```

Open `http://localhost:7070`.

> **Tip**: on Apple Silicon, `SNVR_DEVICE=mps` gives a significant speedup over CPU. Set it in `.env` before starting.

---

## Option 3 — Native Python on Mac (dev / testing)

```bash
git clone https://github.com/gilboash/smart-nvr-ha-trig.git
cd smart-nvr-ha-trig

python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
# Edit .env as needed

./scripts/dev_run.sh
```

Open `http://localhost:7070`.

`dev_run.sh` starts uvicorn with `--reload` so code changes apply immediately without restarting.

Set `SNVR_DEVICE=mps` in `.env` for Apple Silicon inference acceleration.

---

## Option 4 — Native Python on Windows (testing, no Docker)

Requires Python 3.11+ installed and added to PATH.

```powershell
git clone https://github.com/gilboash/smart-nvr-ha-trig.git
cd smart-nvr-ha-trig

python -m venv .venv
.\.venv\Scripts\activate
pip install --upgrade pip
pip install -e ".[dev]"

copy .env.example .env
# Edit .env as needed

python -m uvicorn app.main:app --host 0.0.0.0 --port 7070 --reload
```

Open `http://localhost:7070` locally or `http://<windows-ip>:7070` from other devices. Run `ipconfig` to find your IP.

For NVIDIA GPU acceleration, set `SNVR_DEVICE=cuda:0` in `.env`.

---

## Configuration

All camera and zone config is stored in SQLite and managed from the web UI. The `.env` file controls startup behaviour. You can edit `.env` directly or use the **Settings** page in the UI — it writes back to the file and shows a restart reminder.

| Variable | Default | Description |
|---|---|---|
| `SNVR_PORT` | `7070` | Web UI listening port |
| `SNVR_DB_PATH` | `./data/snvr.db` | SQLite database |
| `SNVR_SNAPSHOT_DIR` | `./data/snapshots` | Episode snapshot storage |
| `SNVR_MODEL_DIR` | `./config/models` | YOLO model weights directory |
| `SNVR_DEVICE` | `auto` | Inference device: `auto`, `cuda:0`, `mps`, `cpu` |
| `SNVR_LOG_LEVEL` | `INFO` | Log verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `SNVR_ADMIN_PASSWORD` | _(auto)_ | Admin password — auto-generated and logged on first boot if blank |
| `SNVR_SESSION_SECRET` | _(auto)_ | Session signing key — set a long random string in production |
| `SNVR_MQTT_HOST` | _(blank)_ | Mosquitto/MQTT broker IP — leave blank to disable HA integration |
| `SNVR_MQTT_PORT` | `1883` | MQTT broker port |
| `SNVR_MQTT_USERNAME` | _(blank)_ | MQTT username |
| `SNVR_MQTT_PASSWORD` | _(blank)_ | MQTT password |
| `SNVR_MQTT_DISCOVERY_PREFIX` | `homeassistant` | HA MQTT discovery prefix |
| `SNVR_MQTT_TOPIC_PREFIX` | `naco_nvr` | State topic prefix |
| `SNVR_STATE_CHECK_INTERVAL` | `10` | Seconds between state zone classification cycles |

YOLO model weights (`yolov8n.pt`) are downloaded automatically on first run if not present in `SNVR_MODEL_DIR`. In Docker the model is saved to the mounted `/models` volume and persists across restarts.

---

## Home Assistant MQTT integration

1. Make sure Mosquitto add-on is running in HA and MQTT integration is configured.
2. Add to `.env`:
   ```
   SNVR_MQTT_HOST=192.168.x.x
   SNVR_MQTT_USERNAME=your_user
   SNVR_MQTT_PASSWORD=your_password
   ```
3. Restart the container: `docker compose up -d`
4. Check logs for: `MQTT connected to 192.168.x.x:1883`
5. In HA go to **Settings → Devices & Services → MQTT** — your cameras appear as devices automatically, one entity per zone.

Zone types in HA:
- **Detection zone** → `binary_sensor` (ON while object present, OFF after hysteresis)
- **State zone** → `sensor` (current label, e.g. `open` / `closed` / `unknown`)

---

## Training state zones (few-shot)

State zones classify a fixed area of the camera image (e.g. a door, blind, or window) without needing cloud APIs or a custom ML model.

1. On the camera edit page, draw a zone and select **State (few-shot)**.
2. Enter two label names (e.g. `open` / `closed`).
3. Set the **MQTT threshold** — confidence below this reports `unknown` to HA instead of a wrong label.
4. Click **Save polygon**.
5. Click **Train** on the zone row.
6. Point the camera at each state and click **Capture** 3–5 times per label.
7. The zone activates immediately — no restart needed.

The raw classifier confidence is always shown in the **Current state** column of the UI regardless of the threshold, so you can tune the threshold after observing real readings.

---

## Notes

- **Concurrent RTSP sessions**: cheap cameras cap at 1–2 sessions. If Frigate already holds the main stream, point this at the sub-stream — or use go2rtc to restream so multiple readers can connect.
- **Custom YOLO models**: place any `.pt` file in `config/models/` (or the Docker `/models` volume) and set the **Model** field on a camera to its filename. Useful for detecting classes not in COCO (e.g. pets, specific objects).
- **State zones as motion detector alternative**: use a detection zone for roaming objects (person, car), and a state zone for things that don't move but change appearance (blinds, doors, indicator lights).
- **Running alongside Frigate**: reads RTSP independently, no exclusive lock. Watch the camera's concurrent session limit.
