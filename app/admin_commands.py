"""Lệnh quản trị qua chat — admin thao tác user/dự án ngay trong chat (Telegram/Google Chat).

Mọi user:
  /help · /whoami
  /repos                        — liệt kê dự án (repo) của tenant
  /repo <số|tên>                — chọn dự án để gửi yêu cầu (khi tenant nhiều repo)
Chỉ admin:
  /users · /role <id> <role> · /unlink <id>
  /invite <role> <tên...>       — tạo user mới + link_token
  /addrepo <owner/repo> <installation_id> [base] [prod] — thêm dự án mới

role ∈ employee|manager|admin. Mọi thao tác giới hạn trong tenant của người gọi.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.channels.base import ChannelAdapter
from app.models import Repository, Tenant, User, UserRole
from app.onboarding import add_repository, create_user, regenerate_link_token

log = logging.getLogger("luna.admin")

_ADMIN_CMDS = {"/users", "/invite", "/role", "/unlink", "/addrepo"}
HELP_TEXT = (
    "🛠 Lệnh:\n"
    "/whoami — thông tin của anh/chị\n"
    "/clear — đóng yêu cầu đang mở, bắt đầu session mới\n"
    "/repos — liệt kê dự án (repo) của tenant\n"
    "/repo <tên|số> — chọn dự án để gửi yêu cầu\n"
    "/users — liệt kê user (admin)\n"
    "/invite <role> <tên> — tạo user + link (admin)\n"
    "/addrepo <owner/repo> <installation_id> [base] [prod] — thêm dự án (admin)\n"
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
        await send(HELP_TEXT)
        return
    if cmd == "/whoami":
        await send(f"id={user.id} · vai trò={user.role.value} · tenant={user.tenant_id} · {user.display_name or ''}")
        return
    if cmd == "/repos":                       # mọi user: xem dự án của tenant
        await _list_repos(db, send, user)
        return
    if cmd == "/repo":                        # mọi user: chọn dự án active
        await _set_active_repo(db, send, user, parts)
        return

    if cmd not in _ADMIN_CMDS:
        await send(f"Lệnh không rõ.\n\n{HELP_TEXT}")
        return

    if user.role != UserRole.ADMIN:
        await send("⛔ Chỉ admin dùng được lệnh này. (Xem /whoami)")
        return

    if cmd == "/users":
        await _list_users(db, send, user.tenant_id)
    elif cmd == "/invite":
        await _invite(db, send, user.tenant_id, parts)
    elif cmd == "/addrepo":
        await _add_repo(db, send, user.tenant_id, parts)
    elif cmd == "/role":
        await _set_role(db, send, user.tenant_id, parts)
    elif cmd == "/unlink":
        await _unlink(db, send, user.tenant_id, parts)


def _tenant_repos(db, tenant_id) -> list[Repository]:
    return list(db.scalars(
        select(Repository).where(Repository.tenant_id == tenant_id).order_by(Repository.id)
    ).all())


async def _list_repos(db, send, user: User) -> None:
    repos = _tenant_repos(db, user.tenant_id)
    if not repos:
        await send("Tenant chưa có dự án nào. Admin thêm bằng /addrepo.")
        return
    lines = [
        f"{'✅' if r.id == user.active_repo_id else '▫️'} {i}. {r.repo_full_name} "
        f"({r.base_branch}→{r.prod_branch})"
        for i, r in enumerate(repos, 1)
    ]
    await send("📦 Dự án:\n" + "\n".join(lines) + "\n\nChọn: /repo <số hoặc tên>")


async def _set_active_repo(db, send, user: User, parts) -> None:
    if len(parts) < 2:
        await send("Cú pháp: /repo <số hoặc tên>. Xem danh sách: /repos")
        return
    repos = _tenant_repos(db, user.tenant_id)
    key = " ".join(parts[1:]).strip()
    chosen = None
    if key.isdigit() and 1 <= int(key) <= len(repos):
        chosen = repos[int(key) - 1]
    else:
        chosen = next((r for r in repos if r.repo_full_name == key
                       or r.repo_full_name.split("/")[-1] == key), None)
    if chosen is None:
        await send(f"Không tìm thấy dự án '{key}'. Xem /repos.")
        return
    user.active_repo_id = chosen.id
    db.commit()
    await send(f"✅ Đã chọn dự án: {chosen.repo_full_name}. Gửi yêu cầu bảo trì để bắt đầu.")


async def _add_repo(db, send, tenant_id, parts) -> None:
    if len(parts) < 3 or "/" not in parts[1] or not parts[2].isdigit():
        await send("Cú pháp: /addrepo <owner/repo> <installation_id> [base_branch] [prod_branch]")
        return
    repo_name, installation_id = parts[1], int(parts[2])
    base = parts[3] if len(parts) > 3 else "dev"
    prod = parts[4] if len(parts) > 4 else "main"
    tenant = db.get(Tenant, tenant_id)
    if db.scalar(select(Repository).where(
            Repository.tenant_id == tenant_id, Repository.repo_full_name == repo_name)):
        await send(f"Dự án {repo_name} đã tồn tại trong tenant.")
        return
    r = add_repository(db, tenant, repo_name, installation_id, base_branch=base, prod_branch=prod)
    db.commit()
    await send(f"✅ Đã thêm dự án #{r.id} {repo_name} ({base}→{prod}).\n"
               "Nhắc cài GitHub App lên repo + repo có 2 nhánh đó. User chọn bằng /repo.")


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
