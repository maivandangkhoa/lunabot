"""Cấp / thu hồi quyền super admin nền tảng (bảng platform_admins).

Super admin xác định theo GitHub id (đúng danh tính đăng nhập web qua OAuth). Vì chưa có
bảng "tài khoản web", seed admin đầu tiên bằng tay qua script này. Nhận diện theo:
  - số  → coi là github_id trực tiếp.
  - chuỗi → tra owner_github_login trong bảng tenants (người đã từng tạo bot/đăng nhập).

    python -m app.grant_admin maivandangkhoa     # cấp theo login (đã có tenant)
    python -m app.grant_admin 123456 --login foo # cấp theo id, gắn login để dễ đọc
    python -m app.grant_admin maivandangkhoa --revoke
    python -m app.grant_admin --list
"""
from __future__ import annotations

import sys

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import PlatformAdmin, Tenant


def _resolve(db: Session, ident: str, login_opt: str | None) -> tuple[int, str | None] | None:
    """(github_id, github_login) từ ident. Số ⇒ id trực tiếp; chuỗi ⇒ tra tenants.owner_github_login."""
    if ident.isdigit():
        return int(ident), login_opt
    tn = db.scalar(
        select(Tenant).where(func.lower(Tenant.owner_github_login) == ident.lower())
        .where(Tenant.owner_github_id.is_not(None))
    )
    if tn is None:
        return None
    return int(tn.owner_github_id), login_opt or tn.owner_github_login


def grant(db: Session, github_id: int, github_login: str | None) -> bool:
    """Thêm super admin nếu chưa có. True = vừa thêm, False = đã tồn tại (idempotent)."""
    existing = db.scalar(select(PlatformAdmin).where(PlatformAdmin.github_id == github_id))
    if existing:
        if github_login and existing.github_login != github_login:
            existing.github_login = github_login
            db.commit()
        return False
    db.add(PlatformAdmin(github_id=github_id, github_login=github_login))
    db.commit()
    return True


def revoke(db: Session, github_id: int) -> bool:
    row = db.scalar(select(PlatformAdmin).where(PlatformAdmin.github_id == github_id))
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def _list(db: Session) -> None:
    rows = db.scalars(select(PlatformAdmin).order_by(PlatformAdmin.id)).all()
    if not rows:
        print("(chưa có super admin nào)")
        return
    for a in rows:
        print(f"  {a.github_id}\t@{a.github_login or '?'}")


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    flags = {a for a in argv if a.startswith("--")}
    login_opt = None
    if "--login" in argv:
        i = argv.index("--login")
        login_opt = argv[i + 1] if i + 1 < len(argv) else None
        args = [a for a in args if a != login_opt]

    db = SessionLocal()
    try:
        if "--list" in flags:
            _list(db)
            return 0
        if not args:
            print(__doc__)
            return 2
        resolved = _resolve(db, args[0], login_opt)
        if resolved is None:
            print(f"Không tìm thấy github_id cho '{args[0]}'. Truyền github_id dạng số, "
                  f"hoặc dùng login của người đã từng đăng nhập/tạo bot.")
            return 1
        github_id, github_login = resolved
        if "--revoke" in flags:
            ok = revoke(db, github_id)
            print(f"{'Đã thu hồi' if ok else 'Không có'} super admin github_id={github_id}.")
        else:
            added = grant(db, github_id, github_login)
            who = f"github_id={github_id}" + (f" (@{github_login})" if github_login else "")
            print(f"{'Đã cấp' if added else 'Đã là'} super admin: {who}.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
