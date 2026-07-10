"""Continuous DVR recording API."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from app.db import get_conn

router = APIRouter(prefix="/recordings", tags=["recordings"])


@router.get("")
async def list_recordings(
    camera_id: int | None = None,
    from_ts: float | None = None,
    to_ts: float | None = None,
    limit: int = 100,
) -> list[dict]:
    conn = get_conn()
    clauses = ["end_ts IS NOT NULL"]
    params: list = []
    if camera_id is not None:
        clauses.append("camera_id = ?")
        params.append(camera_id)
    if from_ts is not None:
        clauses.append("start_ts >= ?")
        params.append(from_ts)
    if to_ts is not None:
        clauses.append("start_ts <= ?")
        params.append(to_ts)
    where = " AND ".join(clauses)
    params.append(limit)
    rows = conn.execute(
        f"SELECT * FROM recordings WHERE {where} ORDER BY start_ts DESC LIMIT ?",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/stats")
async def recording_stats() -> dict:
    from pathlib import Path as _Path
    from app.settings import settings as _s
    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(*) AS cnt, MIN(start_ts) AS oldest, MAX(start_ts) AS newest "
        "FROM recordings WHERE end_ts IS NOT NULL"
    ).fetchone()

    seg_rows = conn.execute(
        "SELECT r.camera_id, c.name AS camera_name, r.path "
        "FROM recordings r JOIN cameras c ON c.id = r.camera_id "
        "WHERE r.end_ts IS NOT NULL"
    ).fetchall()

    cam_stats: dict[int, dict] = {}
    total_bytes = 0
    for sr in seg_rows:
        cid = sr["camera_id"]
        if cid not in cam_stats:
            cam_stats[cid] = {"camera_id": cid, "camera_name": sr["camera_name"],
                               "segment_count": 0, "disk_bytes": 0}
        cam_stats[cid]["segment_count"] += 1
        try:
            sz = _Path(sr["path"]).stat().st_size
            cam_stats[cid]["disk_bytes"] += sz
            total_bytes += sz
        except OSError:
            pass

    per_camera = sorted(cam_stats.values(), key=lambda c: c["disk_bytes"], reverse=True)
    return {
        "count": row["cnt"] or 0,
        "oldest_ts": row["oldest"],
        "newest_ts": row["newest"],
        "disk_bytes": total_bytes,
        "recordings_dir": str(_s.recordings_dir),
        "max_age_days": _s.recording_max_age_days,
        "per_camera": per_camera,
    }


@router.get("/timeline")
async def timeline(camera_id: int | None = None, range_s: int = 86400) -> dict:
    conn = get_conn()
    now = time.time()
    start = now - range_s

    seg_clauses = ["r.start_ts >= ?"]
    seg_params: list = [start]
    if camera_id is not None:
        seg_clauses.append("r.camera_id = ?")
        seg_params.append(camera_id)
    seg_where = " AND ".join(seg_clauses)

    segs = conn.execute(
        f"""
        SELECT r.id, r.camera_id, r.start_ts, r.end_ts, c.name AS camera_name
        FROM recordings r
        LEFT JOIN cameras c ON c.id = r.camera_id
        WHERE {seg_where}
        ORDER BY r.camera_id, r.start_ts
        """,
        seg_params,
    ).fetchall()

    ev_clauses = [
        "e.start_ts >= ?",
        "e.class_name NOT LIKE 'state:%'",
        "(e.zone_id IS NULL OR z.clip_enabled IS NULL OR z.clip_enabled = 1)",
    ]
    ev_params: list = [start]
    if camera_id is not None:
        ev_clauses.append("e.camera_id = ?")
        ev_params.append(camera_id)
    ev_where = " AND ".join(ev_clauses)

    events = conn.execute(
        f"""
        SELECT e.id AS episode_id, e.camera_id, e.class_name, e.start_ts,
               z.name AS zone_name, c.name AS camera_name
        FROM episodes e
        LEFT JOIN zones z ON z.id = e.zone_id
        LEFT JOIN cameras c ON c.id = e.camera_id
        WHERE {ev_where}
        ORDER BY e.start_ts
        """,
        ev_params,
    ).fetchall()

    return {
        "range_start": start,
        "range_end": now,
        "segments": [
            {
                "id": r["id"],
                "camera_id": r["camera_id"],
                "camera_name": r["camera_name"] or f"#{r['camera_id']}",
                "start_ts": r["start_ts"],
                "end_ts": r["end_ts"],
            }
            for r in segs
        ],
        "events": [
            {
                "episode_id": r["episode_id"],
                "camera_id": r["camera_id"],
                "camera_name": r["camera_name"] or f"#{r['camera_id']}",
                "class_name": r["class_name"],
                "zone_name": r["zone_name"],
                "start_ts": r["start_ts"],
            }
            for r in events
        ],
    }


@router.get("/{rec_id}/video")
async def get_video(rec_id: int):
    conn = get_conn()
    row = conn.execute(
        "SELECT path, end_ts FROM recordings WHERE id = ?", (rec_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "recording not found")
    if row["end_ts"] is None:
        raise HTTPException(404, "recording not yet finalized")
    path = Path(row["path"])
    if not path.exists():
        raise HTTPException(404, "recording file not found on disk")
    return FileResponse(str(path), media_type="video/mp4")


@router.post("/cleanup")
async def trigger_cleanup(request: Request) -> dict:
    from app.events.snapshot_store import SnapshotStore
    manager = getattr(request.app.state, "manager", None)
    if manager is None or not hasattr(manager, "continuous_recorder"):
        raise HTTPException(503, "recorder not available")
    rec_removed = await asyncio.to_thread(manager.continuous_recorder.cleanup_old)
    snap_removed = await asyncio.to_thread(SnapshotStore().cleanup_old)
    return {"removed": rec_removed + snap_removed, "recordings": rec_removed, "snapshots": snap_removed}
