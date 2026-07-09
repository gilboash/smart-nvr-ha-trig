from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.db import get_conn, tx

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
