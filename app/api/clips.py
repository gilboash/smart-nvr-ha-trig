from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from app.db import get_conn, tx
from app.settings import settings

router = APIRouter(prefix="/clips", tags=["clips"])

_BASE_SELECT = (
    "SELECT cl.*, c.name AS camera_name, z.name AS zone_name "
    "FROM clips cl "
    "JOIN cameras c ON c.id = cl.camera_id "
    "LEFT JOIN zones z ON z.id = cl.zone_id "
)


@router.get("")
async def list_clips(
    camera_id: int | None = None,
    zone_id: int | None = None,
    after_ts: float | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    where, params = [], []
    if camera_id is not None:
        where.append("cl.camera_id = ?")
        params.append(camera_id)
    if zone_id is not None:
        where.append("cl.zone_id = ?")
        params.append(zone_id)
    if after_ts is not None:
        where.append("cl.created_at >= ?")
        params.append(after_ts)
    sql = _BASE_SELECT
    if where:
        sql += "WHERE " + " AND ".join(where) + " "
    sql += "ORDER BY cl.created_at DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    rows = get_conn().execute(sql, params).fetchall()
    return [dict(r) for r in rows]


@router.get("/summary")
async def clips_summary() -> list[dict]:
    """Cameras (and their zones) that have at least one clip — for filter dropdowns."""
    rows = get_conn().execute(
        """
        SELECT cl.camera_id, c.name AS camera_name,
               cl.zone_id, z.name AS zone_name, COUNT(*) AS clip_count
        FROM clips cl
        JOIN cameras c ON c.id = cl.camera_id
        LEFT JOIN zones z ON z.id = cl.zone_id
        GROUP BY cl.camera_id, cl.zone_id
        ORDER BY c.name, COALESCE(z.name, '')
        """
    ).fetchall()
    cameras: dict[int, dict] = {}
    for r in rows:
        cid = r["camera_id"]
        if cid not in cameras:
            cameras[cid] = {"camera_id": cid, "camera_name": r["camera_name"], "zones": []}
        if r["zone_id"] is not None:
            cameras[cid]["zones"].append({
                "zone_id": r["zone_id"],
                "zone_name": r["zone_name"] or "—",
                "clip_count": r["clip_count"],
            })
    return list(cameras.values())


@router.get("/stats")
async def clip_stats() -> dict:
    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(*) AS cnt, MIN(created_at) AS oldest, MAX(created_at) AS newest FROM clips"
    ).fetchone()

    # Per-camera breakdown: sum actual file sizes from DB paths
    clip_rows = conn.execute(
        "SELECT cl.camera_id, c.name AS camera_name, cl.path "
        "FROM clips cl JOIN cameras c ON c.id = cl.camera_id"
    ).fetchall()
    cam_stats: dict[int, dict] = {}
    total_bytes = 0
    for cr in clip_rows:
        cid = cr["camera_id"]
        if cid not in cam_stats:
            cam_stats[cid] = {"camera_id": cid, "camera_name": cr["camera_name"],
                               "clip_count": 0, "disk_bytes": 0}
        cam_stats[cid]["clip_count"] += 1
        for p in (Path(cr["path"]), Path(cr["path"]).with_suffix(".jpg")):
            try:
                sz = p.stat().st_size
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
        "clips_dir": str(settings.clips_dir),
        "max_age_days": settings.clip_max_age_days,
        "per_camera": per_camera,
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
