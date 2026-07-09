from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from app.db import get_conn, tx
from app.settings import settings

router = APIRouter(prefix="/clips", tags=["clips"])


@router.get("")
async def list_clips(camera_id: int | None = None, limit: int = 50, offset: int = 0) -> list[dict]:
    conn = get_conn()
    if camera_id is not None:
        rows = conn.execute(
            "SELECT cl.*, c.name AS camera_name FROM clips cl "
            "JOIN cameras c ON c.id = cl.camera_id "
            "WHERE cl.camera_id = ? ORDER BY cl.created_at DESC LIMIT ? OFFSET ?",
            (camera_id, limit, offset),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT cl.*, c.name AS camera_name FROM clips cl "
            "JOIN cameras c ON c.id = cl.camera_id "
            "ORDER BY cl.created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    return [dict(r) for r in rows]


# Literal routes must come before parameterized ones
@router.get("/stats")
async def clip_stats() -> dict:
    row = get_conn().execute(
        "SELECT COUNT(*) AS cnt, MIN(created_at) AS oldest, MAX(created_at) AS newest FROM clips"
    ).fetchone()
    total_bytes = 0
    clips_dir = settings.clips_dir
    if clips_dir.is_dir():
        for f in clips_dir.iterdir():
            if f.is_file():
                try:
                    total_bytes += f.stat().st_size
                except OSError:
                    pass
    return {
        "count": row["cnt"] or 0,
        "oldest_ts": row["oldest"],
        "newest_ts": row["newest"],
        "disk_bytes": total_bytes,
        "clips_dir": str(clips_dir),
        "max_age_days": settings.clip_max_age_days,
    }


@router.post("/cleanup")
async def run_cleanup(request: Request) -> dict:
    manager = getattr(request.app.state, "manager", None)
    if manager is None:
        raise HTTPException(503, "pipeline not ready")
    cr = getattr(manager, "clip_recorder", None)
    if cr is None:
        raise HTTPException(503, "clip recorder not available")
    removed = cr.cleanup_old()
    return {"removed": removed}


@router.get("/{clip_id}/thumb.jpg")
async def get_clip_thumb(clip_id: int):
    row = get_conn().execute("SELECT path FROM clips WHERE id = ?", (clip_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "clip not found")
    thumb_path = Path(row["path"]).with_suffix(".jpg")
    if not thumb_path.exists():
        raise HTTPException(404, "thumbnail not available")
    return FileResponse(str(thumb_path), media_type="image/jpeg")


@router.get("/{clip_id}/video.mp4")
async def get_clip_video(clip_id: int):
    row = get_conn().execute("SELECT path FROM clips WHERE id = ?", (clip_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "clip not found")
    path = Path(row["path"])
    if not path.exists():
        raise HTTPException(404, "clip file missing from disk")
    return FileResponse(str(path), media_type="video/mp4", filename=path.name)


@router.delete("/{clip_id}", status_code=204)
async def delete_clip(clip_id: int):
    row = get_conn().execute("SELECT path FROM clips WHERE id = ?", (clip_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "clip not found")
    with tx() as conn:
        conn.execute("DELETE FROM clips WHERE id = ?", (clip_id,))
    try:
        os.remove(row["path"])
    except OSError:
        pass
    try:
        thumb = Path(row["path"]).with_suffix(".jpg")
        if thumb.exists():
            thumb.unlink()
    except OSError:
        pass
