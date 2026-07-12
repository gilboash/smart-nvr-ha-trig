from __future__ import annotations

import asyncio
import logging

import cv2
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.db import get_conn
from app.pipeline.overlay import Detection, draw
from app.settings import settings

router = APIRouter()
logger = logging.getLogger("snvr.ws")


@router.websocket("/ws/events")
async def ws_events(ws: WebSocket) -> None:
    await ws.accept()
    manager = ws.app.state.manager
    broadcaster = manager.ws_broadcaster
    await broadcaster.add(ws)
    try:
        while True:
            # Server pushes only — but read to detect disconnect.
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("ws_events error")
    finally:
        await broadcaster.remove(ws)


@router.websocket("/ws/preview/{camera_id}")
async def ws_preview(ws: WebSocket, camera_id: int, boxes: int = Query(1)) -> None:
    row = get_conn().execute("SELECT id FROM cameras WHERE id = ?", (camera_id,)).fetchone()
    if row is None:
        await ws.close(code=4404)
        return
    await ws.accept()

    manager = ws.app.state.manager
    interval = 1.0 / max(settings.preview_fps, 0.1)
    with_boxes = bool(boxes)

    max_w = settings.preview_max_width

    loop = asyncio.get_event_loop()

    def _encode_frame(bgr, dets):
        h, w = bgr.shape[:2]
        if max_w > 0 and w > max_w:
            scale = max_w / w
            frame = cv2.resize(bgr, (max_w, int(h * scale)), interpolation=cv2.INTER_LINEAR)
            # Scale detection coordinates to match the resized frame
            if with_boxes and dets:
                dets = [
                    Detection(
                        class_name=d.class_name,
                        confidence=d.confidence,
                        bbox_xyxy=(
                            int(d.bbox_xyxy[0] * scale), int(d.bbox_xyxy[1] * scale),
                            int(d.bbox_xyxy[2] * scale), int(d.bbox_xyxy[3] * scale),
                        ),
                        zone_id=d.zone_id,
                    )
                    for d in dets
                ]
        else:
            frame = bgr.copy()
        if with_boxes and dets:
            frame = draw(frame, dets)
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
        return bytes(buf) if ok else None

    try:
        while True:
            entry = manager.bus.latest_bgr(camera_id)
            if entry is None:
                await asyncio.sleep(interval)
                continue
            _, bgr = entry
            dets = manager._inference.latest_detections(camera_id) if with_boxes and manager._inference else []
            data = await loop.run_in_executor(None, _encode_frame, bgr, dets)
            if data:
                try:
                    await ws.send_bytes(data)
                except Exception:
                    break
            await asyncio.sleep(interval)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("ws_preview error")
