from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SNVR_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=(),
    )

    host: str = "0.0.0.0"
    port: int = 7070
    log_level: str = "INFO"

    db_path: Path = Path("./data/snvr.db")
    snapshot_dir: Path = Path("./data/snapshots")
    model_dir: Path = Path("./config/models")

    device: str = "auto"

    preview_fps: float = 2.0
    frame_queue_max: int = 4
    state_check_interval: float = 10.0  # seconds between VQA queries per zone

    session_secret: str = ""
    admin_password: str = ""

    # Clip recording around detection events (legacy)
    clips_dir: Path = Path("./data/clips")
    clip_pre_s: int = 30           # seconds of pre-trigger footage
    clip_post_s: int = 30          # seconds of post-trigger footage
    clip_max_age_days: int = 30    # delete clips older than N days (0 = keep forever)
    clip_max_s: int = 300          # hard cap on clip length in seconds (0 = no cap)

    # Snapshots (one JPEG per detection episode)
    snapshot_max_age_days: int = 7     # delete snapshots older than N days (0 = keep forever)

    # Continuous DVR recording
    recordings_dir: Path = Path("./data/recordings")
    recording_segment_min: int = 5     # flush a new MP4 segment every N minutes
    recording_max_age_days: int = 7    # rolling retention window (0 = keep forever)

    # MQTT / Home Assistant integration (leave mqtt_host blank to disable)
    mqtt_host: str = ""
    mqtt_port: int = 1883
    mqtt_username: str = ""
    mqtt_password: str = ""
    mqtt_discovery_prefix: str = "homeassistant"
    mqtt_topic_prefix: str = "naco_nvr"


settings = Settings()
