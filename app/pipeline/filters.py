"""Per-camera class + polygon-zone filtering.

Polygons are stored in normalized [0..1] coords; the bbox center is
tested against each zone. A detection may match zero or one zone.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from shapely.geometry import Point, Polygon

from app.db import get_conn


@dataclass
class ZoneShape:
    zone_id: int
    name: str
    polygon: Polygon                    # shapely Polygon for hit-testing
    points: list = field(default_factory=list)  # raw normalized [(x,y),...] for crop_zone
    zone_type: str = "detection"
    state_labels: Optional[list[str]] = None
    state_question: Optional[str] = None


def load_zones(camera_id: int) -> list[ZoneShape]:
    rows = get_conn().execute(
        "SELECT id, name, polygon_json, zone_type, state_labels_json, state_question FROM zones WHERE camera_id = ?",
        (camera_id,),
    ).fetchall()
    shapes: list[ZoneShape] = []
    for r in rows:
        pts = json.loads(r["polygon_json"])
        if len(pts) < 3:
            continue
        zone_type = r["zone_type"] or "detection"
        state_labels = json.loads(r["state_labels_json"]) if r["state_labels_json"] else None
        shapes.append(ZoneShape(
            zone_id=r["id"], name=r["name"],
            polygon=Polygon(pts), points=pts,
            zone_type=zone_type, state_labels=state_labels,
            state_question=r["state_question"] or None,
        ))
    return shapes


def match_zone(bbox_xyxy: tuple[float, float, float, float],
               frame_w: int, frame_h: int,
               zones: list[ZoneShape]) -> Optional[int]:
    if not zones:
        return None
    x1, y1, x2, y2 = bbox_xyxy
    cx = ((x1 + x2) / 2.0) / max(frame_w, 1)
    cy = ((y1 + y2) / 2.0) / max(frame_h, 1)
    p = Point(cx, cy)
    for z in zones:
        if z.polygon.contains(p):
            return z.zone_id
    return None
