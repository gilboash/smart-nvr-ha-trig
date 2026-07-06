"""Few-shot scene classifier using MobileNetV3-Small embeddings.

Each state zone stores example crops (one per label) captured by the user from
the live feed. Classification is cosine similarity to the nearest class centroid.
No cloud API, no custom model download — torchvision is already present via ultralytics.
"""
from __future__ import annotations

import logging
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger("snvr.fewshot")


class FewShotClassifier:
    def __init__(self, device: str = "cpu") -> None:
        self.device = device
        self._extractor = None
        self._transform = None

    def _load(self) -> None:
        if self._extractor is not None:
            return
        import torch
        import torchvision.models as M
        import torchvision.transforms as T

        logger.info("loading MobileNetV3-Small feature extractor on %s", self.device)
        backbone = M.mobilenet_v3_small(weights=M.MobileNet_V3_Small_Weights.DEFAULT)
        # features + avgpool gives a 576-dim embedding; drop the classifier head
        import torch.nn as nn
        self._extractor = nn.Sequential(backbone.features, backbone.avgpool)
        self._extractor.eval()
        self._extractor.to(self.device)
        self._transform = T.Compose([
            T.Resize((224, 224)),
            T.ToTensor(),
            T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ])
        logger.info("few-shot feature extractor ready")

    def embed(self, bgr: np.ndarray) -> np.ndarray:
        """Return L2-normalised 576-dim feature vector for a BGR image."""
        import torch
        self._load()
        from PIL import Image
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        tensor = self._transform(Image.fromarray(rgb)).unsqueeze(0).to(self.device)
        with torch.no_grad():
            feat = self._extractor(tensor).squeeze().cpu().numpy()
        norm = np.linalg.norm(feat)
        return feat / (norm + 1e-8)

    def classify(
        self,
        bgr: np.ndarray,
        class_embeddings: dict[str, list[np.ndarray]],
    ) -> tuple[str, float, list]:
        """Classify bgr crop against stored per-class embeddings.

        Returns (label, confidence[0..1], ranked[[label, confidence], ...]).
        Confidence is the cosine similarity remapped from [-1,1] to [0,1].
        """
        query = self.embed(bgr)
        scores: dict[str, float] = {}
        for label, embs in class_embeddings.items():
            centroid = np.mean(embs, axis=0)
            scores[label] = float(np.dot(query, centroid))

        best = max(scores, key=scores.get)
        conf = round((scores[best] + 1.0) / 2.0, 3)
        ranked = [
            [lbl, round((s + 1.0) / 2.0, 3)]
            for lbl, s in sorted(scores.items(), key=lambda x: -x[1])
        ]
        return best, conf, ranked


def crop_zone(
    bgr: np.ndarray,
    polygon_normalized: list[tuple[float, float]],
) -> Optional[np.ndarray]:
    """Crop the bounding box of a normalized polygon from a BGR frame."""
    h, w = bgr.shape[:2]
    pts = np.array([[int(x * w), int(y * h)] for x, y in polygon_normalized])
    x1, y1 = pts.min(axis=0)
    x2, y2 = pts.max(axis=0)
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    if x2 <= x1 or y2 <= y1:
        return None
    return bgr[y1:y2, x1:x2]
