from __future__ import annotations

import asyncio
import copy
import logging

import cv2
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.db import get_conn
from app.pipeline.overlay import draw
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

    try:
        while True:
            entry = manager.bus.latest_bgr(camera_id)
            if entry is None:
                await asyncio.sleep(interval)
                continue
            _, bgr = entry
            frame = copy.copy(bgr)  # shallow ref; encode may take a moment
            if with_boxes and manager._inference is not None:
                dets = manager._inference.latest_detections(camera_id)
                if dets:
                    frame = draw(frame.copy(), dets)
            ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
            if ok:
                try:
                    await ws.send_bytes(bytes(buf))
                except Exception:
                    break
            await asyncio.sleep(interval)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("ws_preview error")
