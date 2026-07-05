"""CLIP-based zero-shot state classifier.

Crops a zone ROI from a frame and ranks user-defined text labels
(e.g. ["open", "half open", "closed"]) by similarity.
Loaded lazily — only instantiated when state zones exist.
"""
from __future__ import annotations

import logging
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger("snvr.clip")

_MODEL_ID = "openai/clip-vit-base-patch32"


class CLIPClassifier:
    def __init__(self, device: str = "cpu") -> None:
        self.device = device
        self._model = None
        self._processor = None

    def _load(self) -> None:
        if self._model is not None:
            return
        logger.info("loading CLIP model %s on %s", _MODEL_ID, self.device)
        from transformers import CLIPModel, CLIPProcessor
        self._processor = CLIPProcessor.from_pretrained(_MODEL_ID)
        self._model = CLIPModel.from_pretrained(_MODEL_ID)
        try:
            import torch
            self._model = self._model.to(self.device)
        except Exception as e:
            logger.warning("CLIP to(%s) failed: %s — using cpu", self.device, e)
            self.device = "cpu"
        self._model.eval()
        logger.info("CLIP ready")

    def classify(
        self,
        bgr: np.ndarray,
        labels: list[str],
    ) -> tuple[str, float, list[tuple[str, float]]]:
        """Returns (best_label, best_prob, [(label, prob), ...]) sorted by prob desc."""
        self._load()

        import torch
        from PIL import Image

        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb)

        inputs = self._processor(
            text=labels, images=image, return_tensors="pt", padding=True
        )
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = self._model(**inputs)
            probs = outputs.logits_per_image.softmax(dim=1).squeeze(0).cpu().tolist()

        ranked = sorted(zip(labels, probs), key=lambda x: x[1], reverse=True)
        best_label, best_prob = ranked[0]
        return best_label, float(best_prob), [(l, float(p)) for l, p in ranked]


def crop_zone(bgr: np.ndarray, polygon_normalized: list[tuple[float, float]]) -> Optional[np.ndarray]:
    """Crop the bounding box of a normalized polygon from a frame."""
    h, w = bgr.shape[:2]
    pts = np.array([[int(x * w), int(y * h)] for x, y in polygon_normalized])
    x1, y1 = pts.min(axis=0)
    x2, y2 = pts.max(axis=0)
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    if x2 <= x1 or y2 <= y1:
        return None
    return bgr[y1:y2, x1:x2]
