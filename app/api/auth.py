from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from app.auth import (
    create_user,
    delete_user,
    get_user,
    list_users,
    require_user,
    session_user,
    update_password,
    verify_password,
)

router = APIRouter(tags=["auth"])

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent.parent / "web" / "templates"))


@router.post("/api/auth/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    user = get_user(username)
    if not user or not verify_password(password, user["password_hash"]):
        return TEMPLATES.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid username or password"},
            status_code=401,
        )
    request.session["username"] = username
    return RedirectResponse("/", status_code=303)


@router.post("/api/auth/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@router.get("/api/auth/me")
async def me(request: Request) -> dict:
    user = require_user(request)
    return {"username": user}


@router.post("/api/auth/change-password")
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
):
    username = require_user(request)
    user = get_user(username)
    if not verify_password(current_password, user["password_hash"]):
        return TEMPLATES.TemplateResponse(
            "settings.html",
            {"request": request, "username": username, "users": list_users(), "error": "Current password is incorrect"},
            status_code=400,
        )
    if new_password != confirm_password:
        return TEMPLATES.TemplateResponse(
            "settings.html",
            {"request": request, "username": username, "users": list_users(), "error": "New passwords do not match"},
            status_code=400,
        )
    if len(new_password) < 8:
        return TEMPLATES.TemplateResponse(
            "settings.html",
            {"request": request, "username": username, "users": list_users(), "error": "Password must be at least 8 characters"},
            status_code=400,
        )
    update_password(username, new_password)
    return TEMPLATES.TemplateResponse(
        "settings.html",
        {"request": request, "username": username, "users": list_users(), "success": "Password changed successfully"},
    )


@router.post("/api/auth/users")
async def add_user(
    request: Request,
    new_username: str = Form(...),
    new_password: str = Form(...),
):
    require_user(request)
    if len(new_password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    if get_user(new_username):
        raise HTTPException(409, "Username already exists")
    create_user(new_username, new_password)
    return RedirectResponse("/settings", status_code=303)


@router.post("/api/auth/users/{username}/delete")
async def remove_user(request: Request, username: str):
    current = require_user(request)
    if username == current:
        raise HTTPException(400, "Cannot delete your own account")
    delete_user(username)
    return RedirectResponse("/settings", status_code=303)
