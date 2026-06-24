"""Trang Team (/users) — quản lý người dùng + workspace qua web.

Port các thao tác admin từ chat (invite/role/unlink) lên web + đổi tên workspace. Mọi
thao tác cách ly theo owner đăng nhập (owner_github_id). CSRF: HMAC(secret, uid) ổn định
theo phiên; cookie SameSite=lax là lớp chống CSRF chính. Tách khỏi routes.py để giữ
mỗi file ≤500 LOC; dùng lại helper phiên (_auth/_tenants/_form) từ routes.
"""
from __future__ import annotations

import hashlib
import hmac

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Bot, Tenant, User, UserRole
from app.onboarding import create_user, regenerate_link_token
from app.web import pages
from app.web.routes import _auth, _form, _tenants

router = APIRouter(tags=["web-team"])


def _csrf(data: dict, s) -> str:
    """Token CSRF ổn định cho phiên: HMAC(secret, uid). Không cần ghi lại session — hợp lệ
    cho mọi phiên đã đăng nhập."""
    raw = f"csrf:{data.get('uid')}".encode()
    return hmac.new(s.web_session_secret.encode(), raw, hashlib.sha256).hexdigest()[:32]


def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _role(v) -> UserRole | None:
    try:
        return UserRole((v or "").lower())
    except ValueError:
        return None


def _owned_tenant(db: Session, data: dict, tenant_id: int | None) -> Tenant | None:
    """Tenant chỉ thao tác được nếu thuộc owner đang đăng nhập (theo owner_github_id)."""
    if tenant_id is None:
        return None
    t = db.get(Tenant, tenant_id)
    return t if t and t.owner_github_id == int(data["uid"]) else None


def _owned_user(db: Session, data: dict, user_id: int | None) -> User | None:
    if user_id is None:
        return None
    u = db.get(User, user_id)
    return u if u and _owned_tenant(db, data, u.tenant_id) else None


def _invite_binding(db: Session, tn: Tenant) -> tuple[str, int | None]:
    """Suy (platform, bot_id) để user mời khớp đúng bot tenant đã provision (deeplink /start).
    Bot riêng (own) ⇒ bind bot_id; bot Luna chung ⇒ bot_id=None."""
    bot = db.scalar(select(Bot).where(Bot.tenant_id == tn.id).order_by(Bot.id))
    if bot is None:
        return tn.chat_platform, None
    return bot.platform, (bot.id if bot.mode == "own" else None)


@router.get("/users", response_class=HTMLResponse)
async def users(request: Request, db: Session = Depends(get_db)):
    data = _auth(request, db)
    if not data:
        return RedirectResponse("/", status_code=303)
    workspaces = []
    for tn in _tenants(db, data):
        rows = [{"id": u.id, "name": u.display_name, "role": u.role.value,
                 "linked": u.platform_user_id is not None, "token": u.link_token}
                for u in db.scalars(
                    select(User).where(User.tenant_id == tn.id).order_by(User.id)).all()]
        workspaces.append({"id": tn.id, "name": tn.name, "plan": tn.plan, "users": rows})
    csrf = _csrf(data, get_settings())
    return HTMLResponse(pages.team(data.get("name") or data["login"], workspaces, csrf))


async def _guard(request: Request) -> tuple[dict | None, dict]:
    """Xác thực phiên + CSRF cho POST team. Trả (data, form); data=None ⇒ caller redirect."""
    data = _auth(request)
    if not data:
        return None, {}
    form = await _form(request)
    if form.get("csrf") != _csrf(data, get_settings()):
        return None, form
    return data, form


@router.post("/users/invite")
async def users_invite(request: Request, db: Session = Depends(get_db)):
    data, form = await _guard(request)
    if data:
        tn = _owned_tenant(db, data, _int(form.get("tenant_id")))
        role = _role(form.get("role"))
        name = (form.get("name") or "").strip()[:255]
        if tn and role and name:
            platform, bot_id = _invite_binding(db, tn)
            create_user(db, tn, role=role, display_name=name, platform=platform, bot_id=bot_id)
            db.commit()
    return RedirectResponse("/users", status_code=303)


@router.post("/users/role")
async def users_role(request: Request, db: Session = Depends(get_db)):
    data, form = await _guard(request)
    if data:
        target = _owned_user(db, data, _int(form.get("user_id")))
        role = _role(form.get("role"))
        if target and role:
            target.role = role
            db.commit()
    return RedirectResponse("/users", status_code=303)


@router.post("/users/unlink")
async def users_unlink(request: Request, db: Session = Depends(get_db)):
    data, form = await _guard(request)
    if data:
        target = _owned_user(db, data, _int(form.get("user_id")))
        if target:
            regenerate_link_token(db, target)
            db.commit()
    return RedirectResponse("/users", status_code=303)


@router.post("/users/delete")
async def users_delete(request: Request, db: Session = Depends(get_db)):
    """Huỷ lời mời = xoá user PENDING (chưa link). Chỉ user chưa liên kết mới xoá được —
    user đã link có thể đã tạo request (FK requester_user_id NOT NULL) ⇒ xoá sẽ lỗi; muốn
    gỡ hẳn thì unlink trước rồi huỷ."""
    data, form = await _guard(request)
    if data:
        target = _owned_user(db, data, _int(form.get("user_id")))
        if target and target.platform_user_id is None:
            db.delete(target)
            db.commit()
    return RedirectResponse("/users", status_code=303)


@router.post("/tenants/rename")
async def tenants_rename(request: Request, db: Session = Depends(get_db)):
    data, form = await _guard(request)
    if data:
        tn = _owned_tenant(db, data, _int(form.get("tenant_id")))
        name = (form.get("name") or "").strip()[:255]
        if tn and name:
            tn.name = name
            db.commit()
    return RedirectResponse("/users", status_code=303)
