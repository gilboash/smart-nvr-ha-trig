from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app.db import get_conn

router = APIRouter(prefix="/cameras", tags=["snapshots"])


@router.get("/{camera_id}/snapshot.jpg")
async def snapshot(camera_id: int, request: Request) -> Response:
    row = get_conn().execute("SELECT id FROM cameras WHERE id = ?", (camera_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "camera not found")

    manager = getattr(request.app.state, "manager", None)
    if manager is None:
        raise HTTPException(503, "pipeline not ready")

    entry = manager.bus.latest_jpeg(camera_id)
    if entry is None:
        raise HTTPException(503, "no frame yet")
    _, jpeg = entry
    return Response(content=jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})
