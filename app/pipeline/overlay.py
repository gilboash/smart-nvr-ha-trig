"""Draw the latest bboxes on a preview frame."""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class Detection:
    class_name: str
    confidence: float
    bbox_xyxy: tuple[int, int, int, int]
    zone_id: int | None = None


def draw(bgr: np.ndarray, detections: list[Detection]) -> np.ndarray:
    for det in detections:
        x1, y1, x2, y2 = det.bbox_xyxy
        color = (0, 200, 100) if det.zone_id is not None else (0, 165, 255)
        cv2.rectangle(bgr, (x1, y1), (x2, y2), color, 2)
        label = f"{det.class_name} {det.confidence:.2f}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(bgr, (x1, y1 - th - 6), (x1 + tw + 4, y1), color, -1)
        cv2.putText(bgr, label, (x1 + 2, y1 - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    return bgr
