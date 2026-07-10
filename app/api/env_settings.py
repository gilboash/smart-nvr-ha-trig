"""Read and write .env configuration from the Settings page."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/settings", tags=["settings"])

ENV_FILE = Path(".env")  # /app/.env in Docker (mounted from host)

# Keys the UI is allowed to read/write — never expose arbitrary file writes
_ALLOWED = {
    "SNVR_MQTT_HOST", "SNVR_MQTT_PORT", "SNVR_MQTT_USERNAME", "SNVR_MQTT_PASSWORD",
    "SNVR_MQTT_DISCOVERY_PREFIX", "SNVR_MQTT_TOPIC_PREFIX",
    "SNVR_LOG_LEVEL", "SNVR_DEVICE", "SNVR_STATE_CHECK_INTERVAL",
    "SNVR_SESSION_SECRET", "SNVR_ADMIN_PASSWORD",
    "SNVR_CLIP_PRE_S", "SNVR_CLIP_POST_S", "SNVR_CLIP_MAX_AGE_DAYS", "SNVR_CLIP_MAX_S",
    "SNVR_SNAPSHOT_MAX_AGE_DAYS",
    "SNVR_RECORDING_SEGMENT_MIN", "SNVR_RECORDING_MAX_AGE_DAYS",
}


class EnvUpdate(BaseModel):
    values: dict[str, str]


@router.get("/env")
async def get_env() -> dict:
    from app.settings import settings
    return {
        "SNVR_MQTT_HOST": settings.mqtt_host,
        "SNVR_MQTT_PORT": str(settings.mqtt_port),
        "SNVR_MQTT_USERNAME": settings.mqtt_username,
        "SNVR_MQTT_PASSWORD": settings.mqtt_password,
        "SNVR_MQTT_DISCOVERY_PREFIX": settings.mqtt_discovery_prefix,
        "SNVR_MQTT_TOPIC_PREFIX": settings.mqtt_topic_prefix,
        "SNVR_LOG_LEVEL": settings.log_level,
        "SNVR_DEVICE": settings.device,
        "SNVR_STATE_CHECK_INTERVAL": str(settings.state_check_interval),
        "SNVR_SESSION_SECRET": settings.session_secret,
        "SNVR_ADMIN_PASSWORD": settings.admin_password,
        "SNVR_CLIP_PRE_S": str(settings.clip_pre_s),
        "SNVR_CLIP_POST_S": str(settings.clip_post_s),
        "SNVR_CLIP_MAX_AGE_DAYS": str(settings.clip_max_age_days),
        "SNVR_CLIP_MAX_S": str(settings.clip_max_s),
        "SNVR_SNAPSHOT_MAX_AGE_DAYS": str(settings.snapshot_max_age_days),
        "SNVR_RECORDING_SEGMENT_MIN": str(settings.recording_segment_min),
        "SNVR_RECORDING_MAX_AGE_DAYS": str(settings.recording_max_age_days),
    }


@router.post("/env")
async def update_env(body: EnvUpdate) -> dict:
    bad = set(body.values) - _ALLOWED
    if bad:
        raise HTTPException(400, f"Disallowed keys: {sorted(bad)}")
    _write_env(body.values)
    return {"ok": True}


def _write_env(updates: dict[str, str]) -> None:
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    written: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k = stripped.partition("=")[0].strip()
            if k in updates:
                new_lines.append(f"{k}={updates[k]}")
                written.add(k)
                continue
        new_lines.append(line)
    for k, v in updates.items():
        if k not in written:
            new_lines.append(f"{k}={v}")
    ENV_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
