from __future__ import annotations

import time

from fastapi import APIRouter, Request

import psutil

from app.coco_classes import COCO_CLASSES

router = APIRouter(tags=["stats"])


@router.get("/api/stats")
async def get_stats(request: Request) -> dict:
    cpu_pct = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory()

    gpu: dict | None = None
    try:
        import torch
        if torch.cuda.is_available():
            used = torch.cuda.memory_allocated(0)
            reserved = torch.cuda.memory_reserved(0)
            props = torch.cuda.get_device_properties(0)
            gpu = {
                "name": props.name,
                "vram_used_mb": round(used / 1024 / 1024),
                "vram_reserved_mb": round(reserved / 1024 / 1024),
                "vram_total_mb": round(props.total_memory / 1024 / 1024),
            }
    except Exception:
        pass

    manager = getattr(request.app.state, "manager", None)
    inference = getattr(manager, "_inference", None)
    device_str = inference.device if inference is not None else "unknown"

    inference_age = None
    inference_ok = None
    if inference is not None:
        last_ts = getattr(inference, "_last_frame_ts", 0.0)
        if last_ts > 0:
            inference_age = round(time.time() - last_ts, 1)
            inference_ok = inference_age < 30.0

    return {
        "cpu_pct": cpu_pct,
        "ram_used_mb": round(mem.used / 1024 / 1024),
        "ram_total_mb": round(mem.total / 1024 / 1024),
        "ram_pct": mem.percent,
        "gpu": gpu,
        "device": device_str,
        "inference_age_s": inference_age,
        "inference_ok": inference_ok,
    }


@router.get("/api/classes")
async def get_classes() -> list[str]:
    return COCO_CLASSES
