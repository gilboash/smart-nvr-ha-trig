"""SQLite connection + raw-SQL migrations. WAL mode for concurrent reads during writes."""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from typing import Iterator

from app.settings import settings

_local = threading.local()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(
        settings.db_path,
        isolation_level=None,
        check_same_thread=False,
        timeout=30.0,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def get_conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = _connect()
        _local.conn = conn
    return conn


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    conn = get_conn()
    conn.execute("BEGIN")
    try:
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


MIGRATIONS: list[str] = [
    # v1
    # (cameras, zones, episodes, schema_version)
    """
    CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY);
    CREATE TABLE IF NOT EXISTS cameras (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        rtsp_url TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        target_fps REAL NOT NULL DEFAULT 5.0,
        model TEXT NOT NULL DEFAULT 'yolov8n.pt',
        classes_json TEXT NOT NULL DEFAULT '["person"]',
        hysteresis_s REAL NOT NULL DEFAULT 5.0,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS zones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        camera_id INTEGER NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        polygon_json TEXT NOT NULL,
        snapshot_w INTEGER NOT NULL,
        snapshot_h INTEGER NOT NULL,
        created_at REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_zones_camera ON zones(camera_id);
    CREATE TABLE IF NOT EXISTS episodes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        camera_id INTEGER NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
        zone_id INTEGER REFERENCES zones(id) ON DELETE SET NULL,
        class_name TEXT NOT NULL,
        start_ts REAL NOT NULL,
        end_ts REAL,
        max_confidence REAL NOT NULL,
        frame_count INTEGER NOT NULL DEFAULT 1,
        snapshot_path TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_episodes_cam_start ON episodes(camera_id, start_ts DESC);
    CREATE INDEX IF NOT EXISTS idx_episodes_open ON episodes(camera_id, end_ts) WHERE end_ts IS NULL;
    """,
    # v2 — users table for session auth
    """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        created_at REAL NOT NULL
    );
    """,
    # v3 — state classification zones (CLIP)
    """
    ALTER TABLE zones ADD COLUMN zone_type TEXT NOT NULL DEFAULT 'detection';
    ALTER TABLE zones ADD COLUMN state_labels_json TEXT;
    """,
    # v4 — VQA question per state zone (column kept; approach superseded by few-shot)
    """
    ALTER TABLE zones ADD COLUMN state_question TEXT;
    """,
    # v5 — few-shot training samples per state zone
    """
    CREATE TABLE IF NOT EXISTS zone_samples (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        zone_id INTEGER NOT NULL REFERENCES zones(id) ON DELETE CASCADE,
        label TEXT NOT NULL,
        image_data BLOB NOT NULL,
        created_at REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_samples_zone ON zone_samples(zone_id);
    """,
    # v6 — confidence thresholds
    """
    ALTER TABLE cameras ADD COLUMN detection_threshold REAL NOT NULL DEFAULT 0.5;
    ALTER TABLE zones ADD COLUMN state_threshold REAL NOT NULL DEFAULT 0.6;
    """,
    # v7 — clip recordings
    """
    CREATE TABLE IF NOT EXISTS clips (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        episode_id INTEGER REFERENCES episodes(id) ON DELETE SET NULL,
        camera_id INTEGER NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
        zone_id INTEGER REFERENCES zones(id) ON DELETE SET NULL,
        class_name TEXT NOT NULL,
        path TEXT NOT NULL,
        duration_s REAL,
        frame_count INTEGER,
        created_at REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_clips_cam_ts ON clips(camera_id, created_at DESC);
    """,
]


def _current_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    return int(row["v"]) if row and row["v"] is not None else 0


def init_db() -> None:
    conn = get_conn()
    conn.executescript(
        "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY);"
    )
    current = _current_version(conn)
    for i, script in enumerate(MIGRATIONS, start=1):
        if i > current:
            conn.executescript(script)
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (i,))
