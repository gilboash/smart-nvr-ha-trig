from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app.db import get_conn

router = APIRouter(prefix="/cameras", tags=["snapshots"])

_NO_CACHE = {"Cache-Control": "no-store"}


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
    return Response(content=jpeg, media_type="image/jpeg", headers=_NO_CACHE)


@router.get("/{camera_id}/preview.jpg")
async def preview(camera_id: int, request: Request) -> Response:
    """Latest frame with detection boxes and state zone overlays baked in."""
    row = get_conn().execute("SELECT id FROM cameras WHERE id = ?", (camera_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "camera not found")

    manager = getattr(request.app.state, "manager", None)
    if manager is None:
        raise HTTPException(503, "pipeline not ready")

    entry = manager.bus.latest_jpeg(camera_id)
    if entry is None:
        raise HTTPException(503, "no frame yet")

    import cv2 as _cv2
    import numpy as _np
    from app.pipeline.overlay import draw
    from app.pipeline.filters import load_zones

    _, jpeg = entry
    arr = _np.frombuffer(jpeg, _np.uint8)
    bgr = _cv2.imdecode(arr, _cv2.IMREAD_COLOR)
    if bgr is None:
        raise HTTPException(503, "could not decode frame")

    h, w = bgr.shape[:2]
    inference = getattr(manager, "_inference", None)

    if inference is not None:
        # Detection boxes
        draw(bgr, inference.latest_detections(camera_id))

        # State zone overlays
        for zone in load_zones(camera_id):
            if zone.zone_type != "state":
                continue
            pts_px = _np.array(
                [(int(x * w), int(y * h)) for x, y in zone.points], dtype=_np.int32
            )
            _cv2.polylines(bgr, [pts_px], True, (200, 80, 220), 2)

            cx = int(pts_px[:, 0].mean())
            cy = int(pts_px[:, 1].mean())

            result = inference.latest_state(zone.zone_id)
            if result is not None:
                label, prob, _ = result
                text = f"{zone.name}: {label} {prob:.0%}"
            else:
                text = f"{zone.name}: ?"

            (tw, th), _ = _cv2.getTextSize(text, _cv2.FONT_HERSHEY_SIMPLEX, 0.48, 1)
            _cv2.rectangle(bgr, (cx - 2, cy - th - 6), (cx + tw + 4, cy), (200, 80, 220), -1)
            _cv2.putText(bgr, text, (cx, cy - 3), _cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 1)

    from app.settings import settings as _s
    max_w = _s.preview_max_width
    if max_w > 0 and w > max_w:
        scale = max_w / w
        bgr = _cv2.resize(bgr, (max_w, int(h * scale)), interpolation=_cv2.INTER_LINEAR)

    _, out = _cv2.imencode(".jpg", bgr, [_cv2.IMWRITE_JPEG_QUALITY, 75])
    return Response(content=out.tobytes(), media_type="image/jpeg", headers=_NO_CACHE)
