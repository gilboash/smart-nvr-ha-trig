"""CLIP-based zero-shot state classifier via open_clip_torch.

Uses ViT-B/32 (openai weights, safetensors) — no torch.load restriction.
Loaded lazily — only instantiated when state zones exist.
"""
from __future__ import annotations

import logging
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger("snvr.clip")

_MODEL_NAME = "ViT-B-32"
_MODEL_PRETRAINED = "openai"


class CLIPClassifier:
    def __init__(self, device: str = "cpu") -> None:
        self.device = device
        self._model = None
        self._preprocess = None
        self._tokenizer = None
        self._load_failed = False

    def _load(self) -> None:
        if self._model is not None:
            return
        if self._load_failed:
            raise RuntimeError("CLIP unavailable — run: pip install open_clip_torch Pillow")
        logger.info("loading CLIP model %s/%s on %s", _MODEL_NAME, _MODEL_PRETRAINED, self.device)
        try:
            import open_clip
        except ImportError:
            self._load_failed = True
            raise RuntimeError("open_clip_torch not installed — run: pip install open_clip_torch Pillow")
        try:
            precision = "fp16" if self.device != "cpu" else "fp32"
            model, _, preprocess = open_clip.create_model_and_transforms(
                _MODEL_NAME, pretrained=_MODEL_PRETRAINED, device=self.device, precision=precision,
            )
            model.eval()
            self._model = model
            self._preprocess = preprocess
            self._tokenizer = open_clip.get_tokenizer(_MODEL_NAME)
            logger.info("CLIP ready on %s (%s)", self.device, precision)
        except Exception as e:
            self._load_failed = True
            logger.error("CLIP load failed: %s", e)
            raise

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
        image = self._preprocess(Image.fromarray(rgb)).unsqueeze(0).to(self.device)
        text = self._tokenizer(labels).to(self.device)

        with torch.no_grad():
            img_feat = self._model.encode_image(image)
            txt_feat = self._model.encode_text(text)
            img_feat = img_feat / img_feat.norm(dim=-1, keepdim=True)
            txt_feat = txt_feat / txt_feat.norm(dim=-1, keepdim=True)
            probs = (img_feat @ txt_feat.T).softmax(dim=-1).squeeze(0).cpu().tolist()

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
