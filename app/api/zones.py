from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request

from app.db import get_conn, tx
from app.models import Zone, ZoneIn, now_ts

router = APIRouter(tags=["zones"])


@router.get("/cameras/{camera_id}/zones")
async def list_zones(camera_id: int) -> list[Zone]:
    rows = get_conn().execute(
        "SELECT * FROM zones WHERE camera_id = ? ORDER BY id", (camera_id,)
    ).fetchall()
    return [Zone.from_row(r) for r in rows]


@router.post("/cameras/{camera_id}/zones", status_code=201)
async def create_zone(camera_id: int, body: ZoneIn, request: Request) -> Zone:
    cam = get_conn().execute("SELECT id FROM cameras WHERE id = ?", (camera_id,)).fetchone()
    if cam is None:
        raise HTTPException(404, "camera not found")
    with tx() as conn:
        cur = conn.execute(
            """
            INSERT INTO zones (camera_id, name, polygon_json, snapshot_w, snapshot_h, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                camera_id,
                body.name,
                json.dumps([list(p) for p in body.polygon]),
                body.snapshot_w,
                body.snapshot_h,
                now_ts(),
            ),
        )
        zone_id = cur.lastrowid
    _reconcile(request)
    row = get_conn().execute("SELECT * FROM zones WHERE id = ?", (zone_id,)).fetchone()
    return Zone.from_row(row)


@router.delete("/zones/{zone_id}", status_code=204)
async def delete_zone(zone_id: int, request: Request) -> None:
    row = get_conn().execute("SELECT id FROM zones WHERE id = ?", (zone_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "zone not found")
    with tx() as conn:
        conn.execute("DELETE FROM zones WHERE id = ?", (zone_id,))
    _reconcile(request)


def _reconcile(request: Request) -> None:
    manager = getattr(request.app.state, "manager", None)
    if manager is not None:
        manager.reconcile()
