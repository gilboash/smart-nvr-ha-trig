from __future__ import annotations

import json
from fastapi import APIRouter, HTTPException, Request

from app.db import get_conn, tx
from app.models import Camera, CameraIn, CameraPatch, now_ts

router = APIRouter(prefix="/cameras", tags=["cameras"])


def _row(camera_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM cameras WHERE id = ?", (camera_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "camera not found")
    return row


@router.get("")
async def list_cameras() -> list[Camera]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM cameras ORDER BY id").fetchall()
    return [Camera.from_row(r) for r in rows]


@router.post("", status_code=201)
async def create_camera(body: CameraIn, request: Request) -> Camera:
    ts = now_ts()
    with tx() as conn:
        try:
            cur = conn.execute(
                """
                INSERT INTO cameras (name, rtsp_url, enabled, target_fps, model,
                                     classes_json, hysteresis_s, detection_threshold,
                                     record_enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    body.name,
                    body.rtsp_url,
                    int(body.enabled),
                    body.target_fps,
                    body.model,
                    json.dumps(body.classes),
                    body.hysteresis_s,
                    body.detection_threshold,
                    int(body.record_enabled),
                    ts,
                    ts,
                ),
            )
        except Exception as e:
            if "UNIQUE" in str(e):
                raise HTTPException(409, "camera name already exists")
            raise
        cam_id = cur.lastrowid
    _reconcile(request)
    return Camera.from_row(_row(cam_id))


@router.get("/{camera_id}")
async def get_camera(camera_id: int) -> Camera:
    return Camera.from_row(_row(camera_id))


@router.patch("/{camera_id}")
async def patch_camera(camera_id: int, body: CameraPatch, request: Request) -> Camera:
    _row(camera_id)
    fields: list[str] = []
    values: list = []
    data = body.model_dump(exclude_unset=True)
    if "classes" in data:
        data["classes_json"] = json.dumps(data.pop("classes"))
    if "enabled" in data:
        data["enabled"] = int(data["enabled"])
    if "record_enabled" in data:
        data["record_enabled"] = int(data["record_enabled"])
    for k, v in data.items():
        fields.append(f"{k} = ?")
        values.append(v)
    if not fields:
        return Camera.from_row(_row(camera_id))
    fields.append("updated_at = ?")
    values.append(now_ts())
    values.append(camera_id)
    with tx() as conn:
        conn.execute(f"UPDATE cameras SET {', '.join(fields)} WHERE id = ?", values)
    _reconcile(request)
    return Camera.from_row(_row(camera_id))


@router.delete("/{camera_id}", status_code=204)
async def delete_camera(camera_id: int, request: Request):
    _row(camera_id)
    with tx() as conn:
        conn.execute("DELETE FROM cameras WHERE id = ?", (camera_id,))
    _reconcile(request)


@router.post("/{camera_id}/probe")
async def probe_camera(camera_id: int) -> dict:
    row = _row(camera_id)
    import asyncio as _asyncio

    def _do() -> dict:
        import cv2
        cap = cv2.VideoCapture(row["rtsp_url"], cv2.CAP_FFMPEG)
        if not cap.isOpened():
            return {"ok": False, "error": "could not open stream"}
        try:
            ok, frame = cap.read()
            if not ok or frame is None:
                return {"ok": False, "error": "opened but no frame"}
            h, w = frame.shape[:2]
            return {"ok": True, "width": int(w), "height": int(h)}
        finally:
            cap.release()

    return await _asyncio.to_thread(_do)


def _reconcile(request: Request) -> None:
    manager = getattr(request.app.state, "manager", None)
    if manager is not None:
        manager.reconcile()
