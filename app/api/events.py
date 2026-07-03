from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.db import get_conn
from app.models import Episode

router = APIRouter(prefix="/events", tags=["events"])


@router.get("")
async def list_events(
    camera_id: Optional[int] = None,
    since: Optional[float] = None,
    limit: int = 100,
) -> list[Episode]:
    limit = max(1, min(int(limit), 500))
    where: list[str] = []
    args: list = []
    if camera_id is not None:
        where.append("camera_id = ?")
        args.append(camera_id)
    if since is not None:
        where.append("start_ts >= ?")
        args.append(since)
    sql = "SELECT * FROM episodes"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY start_ts DESC LIMIT ?"
    args.append(limit)
    rows = get_conn().execute(sql, args).fetchall()
    return [Episode.from_row(r) for r in rows]


@router.get("/{episode_id}/snapshot.jpg")
async def snapshot(episode_id: int) -> FileResponse:
    row = get_conn().execute(
        "SELECT snapshot_path FROM episodes WHERE id = ?", (episode_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "episode not found")
    path = row["snapshot_path"]
    if not path:
        raise HTTPException(404, "no snapshot for this episode")
    p = Path(path)
    if not p.exists():
        raise HTTPException(404, "snapshot file missing on disk")
    return FileResponse(p, media_type="image/jpeg")
