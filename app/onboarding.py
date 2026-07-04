"""Onboarding & seeding multi-tenant: tạo tenant/repo/user, liên kết tài khoản chat.

Role (employee/manager/admin) do admin tenant gán (seed thủ công cho MVP). Liên kết user:
admin tạo user với `link_token`, nhân viên gửi `/start <token>` → map platform_user_id.
"""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Repository, Tenant, User, UserRole


class AlreadyLinkedError(RuntimeError):
    """Tài khoản chat này đã liên kết với 1 user khác (cùng bot) — không link chồng."""


class InvalidBranchError(ValueError):
    """Tên nhánh không hợp lệ (chặn arg-injection vào lệnh git: giá trị bắt đầu bằng '-'…)."""


# Tên nhánh git hợp lệ + KHÔNG bắt đầu bằng '-' (nếu không `git checkout <val>` hiểu là option).
_BRANCH_RE = re.compile(r"^(?!-)[A-Za-z0-9._/-]{1,200}$")


def valid_branch(name: str) -> str:
    """Chuẩn hoá + kiểm tra tên nhánh trước khi đưa vào lệnh git (chống arg-injection)."""
    n = (name or "").strip()
    if (not _BRANCH_RE.match(n) or ".." in n or n.endswith(".lock")
            or n.endswith("/") or "//" in n):
        raise InvalidBranchError(f"Tên nhánh không hợp lệ: {name!r}")
    return n


def create_tenant(db: Session, name: str, *, plan: str = "free") -> Tenant:
    t = Tenant(name=name, plan=plan)
    db.add(t)
    db.flush()
    return t


def add_repository(
    db: Session, tenant: Tenant, repo_full_name: str, gh_installation_id: int,
    *, base_branch: str = "dev", prod_branch: str = "main",
) -> Repository:
    r = Repository(
        tenant_id=tenant.id, repo_full_name=repo_full_name,
        gh_installation_id=gh_installation_id,
        base_branch=valid_branch(base_branch), prod_branch=valid_branch(prod_branch),
    )
    db.add(r)
    db.flush()
    return r


def create_user(
    db: Session, tenant: Tenant, *, role: UserRole = UserRole.EMPLOYEE,
    display_name: str | None = None, platform: str = "telegram",
    bot_id: int | None = None,
) -> User:
    """Tạo user chưa liên kết, kèm link_token để gửi cho người dùng.

    `bot_id`: bot riêng mà user liên kết tới (None = bot Luna chung). Lookup sau scope theo nó.
    """
    u = User(
        tenant_id=tenant.id, role=role, display_name=display_name,
        platform=platform, bot_id=bot_id, link_token=secrets.token_urlsafe(16),
    )
    db.add(u)
    db.flush()
    return u


def link_user(db: Session, link_token: str, platform_user_id: str,
              platform: str | None = None, bot_id: int | None = None) -> User | None:
    """Liên kết platform_user_id vào user qua link_token.

    `platform`: kênh user THỰC SỰ dùng để /start (vd "google_chat"). Token vốn không gắn
    kênh, nên bind platform tại đây để khớp lookup — tránh lệch khi admin tạo user sai platform.
    `bot_id`: bot mà user vừa /start. Token chỉ dùng được trên ĐÚNG bot đã provision cho user
    (deeplink dẫn tới bot đó) — dùng token trên bot khác ⇒ None (tránh lẫn tenant).
    Vô hiệu hoá token sau khi dùng (chống tái sử dụng). Muốn link lại → cấp token mới.
    """
    u = db.scalars(select(User).where(User.link_token == link_token)).first()
    if u is None:
        return None
    if u.bot_id != bot_id:
        return None
    # Bot chung (bot_id=NULL): Postgres coi NULL distinct ⇒ unique constraint KHÔNG chặn trùng
    # (bot_id, platform, platform_user_id). Chặn ở tầng app: 1 tài khoản chat trên 1 bot chỉ
    # thuộc 1 tenant — nếu danh tính này đã gắn user khác ⇒ từ chối (tránh route nhập nhằng).
    lookup_platform = platform or u.platform
    dup = db.scalars(
        select(User).where(
            User.bot_id == bot_id,
            User.platform == lookup_platform,
            User.platform_user_id == platform_user_id,
            User.id != u.id,
        )
    ).first()
    if dup is not None:
        raise AlreadyLinkedError(
            f"platform_user_id={platform_user_id} đã liên kết user #{dup.id} (tenant {dup.tenant_id})"
        )
    if platform:
        u.platform = platform
    u.platform_user_id = platform_user_id
    u.linked_at = datetime.now(timezone.utc)
    u.link_token = None
    db.flush()
    return u


def regenerate_link_token(db: Session, user: User) -> str:
    """Gỡ liên kết hiện tại + cấp link_token mới (để người dùng /start lại)."""
    user.platform_user_id = None
    user.linked_at = None
    user.link_token = secrets.token_urlsafe(16)
    db.flush()
    return user.link_token


def get_user_by_platform(db: Session, platform: str, platform_user_id: str,
                         bot_id: int | None = None) -> User | None:
    """Tìm user theo (bot_id, platform, platform_user_id). `bot_id=None` = bot Luna chung
    (cô lập với các bot riêng — cùng 1 tài khoản chat có thể nói với nhiều bot khác tenant)."""
    return db.scalars(
        select(User).where(
            User.platform == platform,
            User.platform_user_id == platform_user_id,
            User.bot_id == bot_id,
        )
    ).first()
