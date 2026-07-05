import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request

from app.settings import settings

logger = logging.getLogger("snvr")

WEB_DIR = Path(__file__).parent / "web"
TEMPLATES = Jinja2Templates(directory=str(WEB_DIR / "templates"))

_PUBLIC_PREFIXES = ("/static/", "/api/auth/login", "/api/health")
_PUBLIC_EXACT = {"/login"}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        is_public = path in _PUBLIC_EXACT or any(path.startswith(p) for p in _PUBLIC_PREFIXES)
        if not is_public:
            user = request.session.get("username")
            if not user:
                if path.startswith("/api/") or path.startswith("/ws/"):
                    return JSONResponse({"detail": "not authenticated"}, status_code=401)
                return RedirectResponse("/login")
        return await call_next(request)


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

    from app.auth import ensure_default_admin
    ensure_default_admin(settings.admin_password)

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

_session_secret = settings.session_secret or secrets.token_hex(32)

# Order matters: add_middleware inserts at the front of the stack, so the LAST
# add_middleware call becomes the outermost middleware (runs first).
# We need SessionMiddleware to run before AuthMiddleware so session is populated.
# Therefore: add AuthMiddleware first (inner), SessionMiddleware second (outer).
app.add_middleware(AuthMiddleware)
app.add_middleware(SessionMiddleware, secret_key=_session_secret, max_age=7 * 24 * 3600)

app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")

from app.api import cameras, zones, snapshots, events, ws, stats, auth as auth_router  # noqa: E402

app.include_router(cameras.router, prefix="/api")
app.include_router(zones.router, prefix="/api")
app.include_router(snapshots.router, prefix="/api")
app.include_router(events.router, prefix="/api")
app.include_router(stats.router)
app.include_router(auth_router.router)
app.include_router(ws.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if request.session.get("username"):
        return RedirectResponse("/")
    return TEMPLATES.TemplateResponse("login.html", {"request": request})


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return TEMPLATES.TemplateResponse("dashboard.html", {"request": request, "username": request.session.get("username")})


@app.get("/cameras", response_class=HTMLResponse)
async def cameras_page(request: Request):
    return TEMPLATES.TemplateResponse("cameras.html", {"request": request, "username": request.session.get("username")})


@app.get("/cameras/{camera_id}", response_class=HTMLResponse)
async def camera_edit_page(request: Request, camera_id: int):
    return TEMPLATES.TemplateResponse(
        "camera_edit.html", {"request": request, "camera_id": camera_id, "username": request.session.get("username")}
    )


@app.get("/events", response_class=HTMLResponse)
async def events_page(request: Request):
    return TEMPLATES.TemplateResponse("events.html", {"request": request, "username": request.session.get("username")})


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    from app.auth import list_users
    username = request.session.get("username")
    return TEMPLATES.TemplateResponse(
        "settings.html",
        {"request": request, "username": username, "users": list_users()},
    )
