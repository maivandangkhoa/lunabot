"""Lệnh quản trị qua chat (B) — admin thao tác user ngay trên Telegram.

Lệnh (chỉ role admin, trừ /help, /whoami):
  /help                         — danh sách lệnh
  /whoami                       — id, vai trò, tenant của bạn
  /users                        — liệt kê user trong tenant
  /invite <role> <tên...>       — tạo user mới + trả link_token (/start <token>)
  /role <user_id> <role>        — đổi vai trò user
  /unlink <user_id>             — gỡ liên kết + cấp link_token mới

role ∈ employee|manager|admin. Mọi thao tác giới hạn trong tenant của người gọi.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.channels.base import ChannelAdapter
from app.models import User, UserRole
from app.onboarding import create_user, regenerate_link_token

log = logging.getLogger("luna.admin")

_ADMIN_CMDS = {"/users", "/invite", "/role", "/unlink"}
_HELP = (
    "🛠 Lệnh:\n"
    "/whoami — thông tin của anh/chị\n"
    "/users — liệt kê user (admin)\n"
    "/invite <role> <tên> — tạo user + link (admin)\n"
    "/role <user_id> <role> — đổi vai trò (admin)\n"
    "/unlink <user_id> — gỡ liên kết, cấp token mới (admin)\n"
    "role ∈ employee|manager|admin"
)


def is_command(text: str) -> bool:
    return text.startswith("/")


def _role(s: str) -> UserRole | None:
    try:
        return UserRole(s.lower())
    except ValueError:
        return None


async def handle_command(db: Session, adapter: ChannelAdapter, user: User, text: str) -> None:
    parts = text.split()
    cmd = parts[0].lower()
    send = lambda t: adapter.send(user.platform_user_id, t)  # noqa: E731

    if cmd in ("/help", "/start"):
        await send(_HELP)
        return
    if cmd == "/whoami":
        await send(f"id={user.id} · vai trò={user.role.value} · tenant={user.tenant_id} · {user.display_name or ''}")
        return

    if cmd not in _ADMIN_CMDS:
        await send(f"Lệnh không rõ.\n\n{_HELP}")
        return

    if user.role != UserRole.ADMIN:
        await send("⛔ Chỉ admin dùng được lệnh này. (Xem /whoami)")
        return

    if cmd == "/users":
        await _list_users(db, send, user.tenant_id)
    elif cmd == "/invite":
        await _invite(db, send, user.tenant_id, parts)
    elif cmd == "/role":
        await _set_role(db, send, user.tenant_id, parts)
    elif cmd == "/unlink":
        await _unlink(db, send, user.tenant_id, parts)


async def _list_users(db, send, tenant_id):
    users = db.scalars(select(User).where(User.tenant_id == tenant_id).order_by(User.id)).all()
    lines = [
        f"#{u.id} {u.role.value:8} {u.display_name or '-'} "
        f"[{'đã link' if u.platform_user_id else 'token: ' + (u.link_token or '?')}]"
        for u in users
    ]
    await send("👥 Users:\n" + "\n".join(lines) if lines else "Chưa có user.")


async def _invite(db, send, tenant_id, parts):
    if len(parts) < 3 or _role(parts[1]) is None:
        await send("Cú pháp: /invite <employee|manager|admin> <tên>")
        return
    from app.models import Tenant
    tenant = db.get(Tenant, tenant_id)
    name = " ".join(parts[2:])
    u = create_user(db, tenant, role=_role(parts[1]), display_name=name)
    db.commit()
    await send(f"✅ Tạo {u.role.value} '{name}' (#{u.id}).\nGửi họ: /start {u.link_token}")


async def _set_role(db, send, tenant_id, parts):
    if len(parts) != 3 or not parts[1].isdigit() or _role(parts[2]) is None:
        await send("Cú pháp: /role <user_id> <employee|manager|admin>")
        return
    target = db.get(User, int(parts[1]))
    if target is None or target.tenant_id != tenant_id:
        await send("Không tìm thấy user trong tenant của anh/chị.")
        return
    target.role = _role(parts[2])
    db.commit()
    await send(f"✅ #{target.id} '{target.display_name or ''}' → {target.role.value}")


async def _unlink(db, send, tenant_id, parts):
    if len(parts) != 2 or not parts[1].isdigit():
        await send("Cú pháp: /unlink <user_id>")
        return
    target = db.get(User, int(parts[1]))
    if target is None or target.tenant_id != tenant_id:
        await send("Không tìm thấy user trong tenant của anh/chị.")
        return
    token = regenerate_link_token(db, target)
    db.commit()
    await send(f"✅ Đã gỡ liên kết #{target.id}. Token mới: /start {token}")
