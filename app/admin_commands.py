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
from app.web.i18n import t

log = logging.getLogger("luna.admin")

_ADMIN_CMDS = {"/users", "/invite", "/role", "/unlink", "/addrepo"}


def help_text() -> str:
    return t("admin.help")


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
        await send(help_text())
        return
    if cmd == "/whoami":
        await send(t("admin.whoami", id=user.id, role=user.role.value,
                     tenant=user.tenant_id, name=user.display_name or ""))
        return
    if cmd == "/repos":                       # mọi user: xem dự án của tenant
        await _list_repos(db, send, user)
        return
    if cmd == "/repo":                        # mọi user: chọn dự án active
        await _set_active_repo(db, send, user, parts)
        return

    if cmd not in _ADMIN_CMDS:
        await send(t("admin.unknown_command", help=help_text()))
        return

    if user.role != UserRole.ADMIN:
        await send(t("admin.only_admin"))
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
        await send(t("admin.repos_empty"))
        return
    lines = [
        f"{'✅' if r.id == user.active_repo_id else '▫️'} {i}. {r.repo_full_name} "
        f"({r.base_branch}→{r.prod_branch})"
        for i, r in enumerate(repos, 1)
    ]
    await send(t("admin.repos_list", body="\n".join(lines)))


async def _set_active_repo(db, send, user: User, parts) -> None:
    if len(parts) < 2:
        await send(t("admin.repo_usage"))
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
        await send(t("admin.repo_not_found", key=key))
        return
    user.active_repo_id = chosen.id
    db.commit()
    await send(t("admin.repo_chosen", name=chosen.repo_full_name))


async def _add_repo(db, send, tenant_id, parts) -> None:
    if len(parts) < 3 or "/" not in parts[1] or not parts[2].isdigit():
        await send(t("admin.addrepo_usage"))
        return
    repo_name, installation_id = parts[1], int(parts[2])
    base = parts[3] if len(parts) > 3 else "dev"
    prod = parts[4] if len(parts) > 4 else "main"
    tenant = db.get(Tenant, tenant_id)
    if db.scalar(select(Repository).where(
            Repository.tenant_id == tenant_id, Repository.repo_full_name == repo_name)):
        await send(t("admin.repo_exists", name=repo_name))
        return
    r = add_repository(db, tenant, repo_name, installation_id, base_branch=base, prod_branch=prod)
    db.commit()
    await send(t("admin.repo_added", id=r.id, name=repo_name, base=base, prod=prod))


async def _list_users(db, send, tenant_id):
    users = db.scalars(select(User).where(User.tenant_id == tenant_id).order_by(User.id)).all()
    lines = [
        f"#{u.id} {u.role.value:8} {u.display_name or '-'} "
        f"[{t('admin.user_linked') if u.platform_user_id else t('admin.user_token', token=u.link_token or '?')}]"
        for u in users
    ]
    await send(t("admin.users_header", body="\n".join(lines)) if lines else t("admin.users_empty"))


async def _invite(db, send, tenant_id, parts):
    if len(parts) < 3 or _role(parts[1]) is None:
        await send(t("admin.invite_usage"))
        return
    from app.models import Tenant
    tenant = db.get(Tenant, tenant_id)
    name = " ".join(parts[2:])
    u = create_user(db, tenant, role=_role(parts[1]), display_name=name)
    db.commit()
    await send(t("admin.invite_created", role=u.role.value, name=name, id=u.id, token=u.link_token))


async def _set_role(db, send, tenant_id, parts):
    if len(parts) != 3 or not parts[1].isdigit() or _role(parts[2]) is None:
        await send(t("admin.role_usage"))
        return
    target = db.get(User, int(parts[1]))
    if target is None or target.tenant_id != tenant_id:
        await send(t("admin.user_not_in_tenant"))
        return
    target.role = _role(parts[2])
    db.commit()
    await send(t("admin.role_changed", id=target.id, name=target.display_name or "", role=target.role.value))


async def _unlink(db, send, tenant_id, parts):
    if len(parts) != 2 or not parts[1].isdigit():
        await send(t("admin.unlink_usage"))
        return
    target = db.get(User, int(parts[1]))
    if target is None or target.tenant_id != tenant_id:
        await send(t("admin.user_not_in_tenant"))
        return
    token = regenerate_link_token(db, target)
    db.commit()
    await send(t("admin.unlinked", id=target.id, token=token))
