from __future__ import annotations

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
    device = getattr(manager, "_inference", None)
    device_str = device.device if device is not None else "unknown"

    return {
        "cpu_pct": cpu_pct,
        "ram_used_mb": round(mem.used / 1024 / 1024),
        "ram_total_mb": round(mem.total / 1024 / 1024),
        "ram_pct": mem.percent,
        "gpu": gpu,
        "device": device_str,
    }


@router.get("/api/classes")
async def get_classes() -> list[str]:
    return COCO_CLASSES
