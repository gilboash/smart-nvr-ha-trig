import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from app.settings import settings

logger = logging.getLogger("snvr")

WEB_DIR = Path(__file__).parent / "web"
TEMPLATES = Jinja2Templates(directory=str(WEB_DIR / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings.snapshot_dir.mkdir(parents=True, exist_ok=True)
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)

    from app.db import init_db
    init_db()

    from app.pipeline.manager import PipelineManager
    manager = PipelineManager()
    app.state.manager = manager
    await manager.start()

    logger.info("snvr up on %s:%d", settings.host, settings.port)
    try:
        yield
    finally:
        await manager.stop()


app = FastAPI(title="smart-nvr-ha-trig", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")

from app.api import cameras, zones, snapshots, events, ws  # noqa: E402

app.include_router(cameras.router, prefix="/api")
app.include_router(zones.router, prefix="/api")
app.include_router(snapshots.router, prefix="/api")
app.include_router(events.router, prefix="/api")
app.include_router(ws.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return TEMPLATES.TemplateResponse("dashboard.html", {"request": request})


@app.get("/cameras", response_class=HTMLResponse)
async def cameras_page(request: Request):
    return TEMPLATES.TemplateResponse("cameras.html", {"request": request})


@app.get("/cameras/{camera_id}", response_class=HTMLResponse)
async def camera_edit_page(request: Request, camera_id: int):
    return TEMPLATES.TemplateResponse(
        "camera_edit.html", {"request": request, "camera_id": camera_id}
    )


@app.get("/events", response_class=HTMLResponse)
async def events_page(request: Request):
    return TEMPLATES.TemplateResponse("events.html", {"request": request})
