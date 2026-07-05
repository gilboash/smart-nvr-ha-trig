from __future__ import annotations

import logging
import secrets
import time

import bcrypt
from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse

from app.db import get_conn, tx

logger = logging.getLogger("snvr.auth")

_PUBLIC_PREFIXES = ("/static/", "/api/auth/login", "/api/health")
_PUBLIC_EXACT = {"/login"}


def is_public(path: str) -> bool:
    if path in _PUBLIC_EXACT:
        return True
    return any(path.startswith(p) for p in _PUBLIC_PREFIXES)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except Exception:
        return False


def get_user(username: str) -> dict | None:
    row = get_conn().execute(
        "SELECT * FROM users WHERE username = ?", (username,)
    ).fetchone()
    return dict(row) if row else None


def create_user(username: str, password: str) -> None:
    with tx() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (username, hash_password(password), time.time()),
        )


def update_password(username: str, new_password: str) -> None:
    with tx() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE username = ?",
            (hash_password(new_password), username),
        )


def list_users() -> list[dict]:
    rows = get_conn().execute(
        "SELECT id, username, created_at FROM users ORDER BY id"
    ).fetchall()
    return [dict(r) for r in rows]


def delete_user(username: str) -> None:
    with tx() as conn:
        conn.execute("DELETE FROM users WHERE username = ?", (username,))


def ensure_default_admin(forced_password: str = "") -> None:
    """Create the admin user on first boot. Logs generated password."""
    existing = get_conn().execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
    if existing > 0:
        if forced_password:
            update_password("admin", forced_password)
            logger.info("admin password updated from SNVR_ADMIN_PASSWORD env var")
        return
    password = forced_password or secrets.token_urlsafe(12)
    create_user("admin", password)
    if not forced_password:
        logger.warning("=" * 60)
        logger.warning("FIRST BOOT — default admin credentials:")
        logger.warning("  username: admin")
        logger.warning("  password: %s", password)
        logger.warning("Change this at http://<host>:7070/settings")
        logger.warning("=" * 60)


def session_user(request: Request) -> str | None:
    return request.session.get("username")


def require_user(request: Request) -> str:
    user = session_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="not authenticated")
    return user
