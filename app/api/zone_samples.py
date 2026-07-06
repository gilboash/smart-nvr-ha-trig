from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app.db import get_conn, tx
from app.models import now_ts

router = APIRouter(tags=["zone_samples"])


def _get_inference(request: Request):
    manager = getattr(request.app.state, "manager", None)
    return manager._inference if manager else None


@router.post("/zones/{zone_id}/samples", status_code=201)
async def add_sample(zone_id: int, label: str, request: Request):
    """Save a JPEG crop (raw bytes body) as a training example for this zone+label."""
    row = get_conn().execute("SELECT id FROM zones WHERE id = ?", (zone_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "zone not found")

    body = await request.body()
    if not body:
        raise HTTPException(400, "request body must be JPEG image bytes")

    with tx() as conn:
        cur = conn.execute(
            "INSERT INTO zone_samples (zone_id, label, image_data, created_at) VALUES (?, ?, ?, ?)",
            (zone_id, label, body, now_ts()),
        )
        sample_id = cur.lastrowid

    infer = _get_inference(request)
    if infer is not None:
        infer.invalidate_zone_embeddings(zone_id)

    return {"id": sample_id, "zone_id": zone_id, "label": label}


@router.get("/zones/{zone_id}/samples")
async def list_samples(zone_id: int) -> list[dict]:
    rows = get_conn().execute(
        "SELECT id, label, created_at FROM zone_samples WHERE zone_id = ? ORDER BY id",
        (zone_id,),
    ).fetchall()
    return [{"id": r["id"], "label": r["label"], "created_at": r["created_at"]} for r in rows]


@router.delete("/zones/{zone_id}/samples/{sample_id}", status_code=204)
async def delete_sample(zone_id: int, sample_id: int, request: Request):
    row = get_conn().execute(
        "SELECT id FROM zone_samples WHERE id = ? AND zone_id = ?", (sample_id, zone_id)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "sample not found")
    with tx() as conn:
        conn.execute("DELETE FROM zone_samples WHERE id = ?", (sample_id,))
    infer = _get_inference(request)
    if infer is not None:
        infer.invalidate_zone_embeddings(zone_id)


@router.delete("/zones/{zone_id}/samples", status_code=204)
async def clear_samples(zone_id: int, request: Request):
    """Delete all training samples for a zone."""
    with tx() as conn:
        conn.execute("DELETE FROM zone_samples WHERE zone_id = ?", (zone_id,))
    infer = _get_inference(request)
    if infer is not None:
        infer.invalidate_zone_embeddings(zone_id)
