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

    session_secret: str = ""
    admin_password: str = ""


settings = Settings()
