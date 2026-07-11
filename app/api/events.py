from __future__ import annotations

from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

from app.db import get_conn
from app.models import Episode

router = APIRouter(prefix="/events", tags=["events"])


@router.get("")
async def list_events(
    camera_id: Optional[int] = None,
    since: Optional[float] = None,
    before_ts: Optional[float] = None,
    limit: int = 50,
) -> list[Episode]:
    limit = max(1, min(int(limit), 200))
    where: list[str] = []
    args: list = []
    if camera_id is not None:
        where.append("camera_id = ?")
        args.append(camera_id)
    if since is not None:
        where.append("start_ts >= ?")
        args.append(since)
    if before_ts is not None:
        where.append("start_ts < ?")
        args.append(before_ts)
    sql = "SELECT * FROM episodes"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY start_ts DESC LIMIT ?"
    args.append(limit)
    rows = get_conn().execute(sql, args).fetchall()
    return [Episode.from_row(r) for r in rows]


_THUMB_MAX_W = 480  # thumbnail width cap — keeps browser memory low


@router.get("/{episode_id}/snapshot.jpg")
async def snapshot(episode_id: int) -> Response:
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
    data = p.read_bytes()
    bgr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if bgr is None:
        return Response(data, media_type="image/jpeg")
    h, w = bgr.shape[:2]
    if w > _THUMB_MAX_W:
        bgr = cv2.resize(bgr, (_THUMB_MAX_W, int(h * _THUMB_MAX_W / w)), interpolation=cv2.INTER_LINEAR)
    ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 70])
    if not ok:
        return Response(data, media_type="image/jpeg")
    return Response(bytes(buf), media_type="image/jpeg")
