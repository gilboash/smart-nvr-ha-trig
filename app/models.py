from __future__ import annotations

import json
import time
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class CameraIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    rtsp_url: str = Field(min_length=1)
    enabled: bool = True
    target_fps: float = Field(default=5.0, ge=0.0, le=30.0)
    model: str = "yolov8n.pt"
    classes: list[str] = ["person"]
    hysteresis_s: float = Field(default=5.0, ge=0.5, le=120.0)


class CameraPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=64)
    rtsp_url: Optional[str] = Field(default=None, min_length=1)
    enabled: Optional[bool] = None
    target_fps: Optional[float] = Field(default=None, ge=0.0, le=30.0)
    model: Optional[str] = None
    classes: Optional[list[str]] = None
    hysteresis_s: Optional[float] = Field(default=None, ge=0.5, le=120.0)


class Camera(BaseModel):
    id: int
    name: str
    rtsp_url: str
    enabled: bool
    target_fps: float
    model: str
    classes: list[str]
    hysteresis_s: float
    created_at: float
    updated_at: float

    @classmethod
    def from_row(cls, row) -> "Camera":
        return cls(
            id=row["id"],
            name=row["name"],
            rtsp_url=row["rtsp_url"],
            enabled=bool(row["enabled"]),
            target_fps=row["target_fps"],
            model=row["model"],
            classes=json.loads(row["classes_json"]),
            hysteresis_s=row["hysteresis_s"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class ZoneIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    polygon: list[tuple[float, float]] = Field(min_length=3)
    snapshot_w: int = Field(gt=0)
    snapshot_h: int = Field(gt=0)

    @field_validator("polygon")
    @classmethod
    def _normalized(cls, v: list[tuple[float, float]]):
        for x, y in v:
            if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
                raise ValueError("polygon points must be normalized to [0, 1]")
        return v


class Zone(BaseModel):
    id: int
    camera_id: int
    name: str
    polygon: list[tuple[float, float]]
    snapshot_w: int
    snapshot_h: int
    created_at: float

    @classmethod
    def from_row(cls, row) -> "Zone":
        return cls(
            id=row["id"],
            camera_id=row["camera_id"],
            name=row["name"],
            polygon=json.loads(row["polygon_json"]),
            snapshot_w=row["snapshot_w"],
            snapshot_h=row["snapshot_h"],
            created_at=row["created_at"],
        )


class Episode(BaseModel):
    id: int
    camera_id: int
    zone_id: Optional[int]
    class_name: str
    start_ts: float
    end_ts: Optional[float]
    max_confidence: float
    frame_count: int
    snapshot_path: Optional[str]

    @classmethod
    def from_row(cls, row) -> "Episode":
        return cls(
            id=row["id"],
            camera_id=row["camera_id"],
            zone_id=row["zone_id"],
            class_name=row["class_name"],
            start_ts=row["start_ts"],
            end_ts=row["end_ts"],
            max_confidence=row["max_confidence"],
            frame_count=row["frame_count"],
            snapshot_path=row["snapshot_path"],
        )


def now_ts() -> float:
    return time.time()
