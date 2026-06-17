"""CLI quản trị user/tenant (A) — thao tác trên tenant ĐÃ CÓ (khác seed.py tạo tenant mới).

Ví dụ:
    python -m scripts.user tenants
    python -m scripts.user list --tenant 1
    python -m scripts.user add --tenant 1 --role manager --name "Nguyen Van A"
    python -m scripts.user set-role --user 2 --role admin
    python -m scripts.user unlink --user 2
    python -m scripts.user add-repo --tenant 1 --repo owner/repo --installation 12345
"""
from __future__ import annotations

import argparse

from app.db import SessionLocal
from app.models import Repository, Tenant, User, UserRole
from app.onboarding import add_repository, create_user, regenerate_link_token


def _print_users(db, tenant_id: int | None) -> None:
    q = db.query(User)
    if tenant_id:
        q = q.filter(User.tenant_id == tenant_id)
    for u in q.order_by(User.id):
        state = "linked" if u.platform_user_id else f"token={u.link_token}"
        print(f"#{u.id} t{u.tenant_id} {u.role.value:8} {u.display_name or '-':20} [{state}]")


def main() -> None:
    ap = argparse.ArgumentParser(prog="scripts.user")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("tenants")
    p = sub.add_parser("list"); p.add_argument("--tenant", type=int)
    p = sub.add_parser("add")
    p.add_argument("--tenant", type=int, required=True)
    p.add_argument("--role", choices=[r.value for r in UserRole], default="employee")
    p.add_argument("--name", required=True)
    p.add_argument("--platform", choices=["telegram", "google_chat"], default="telegram",
                   help="kênh chat user dùng để /start (mặc định telegram)")
    p = sub.add_parser("set-role")
    p.add_argument("--user", type=int, required=True)
    p.add_argument("--role", choices=[r.value for r in UserRole], required=True)
    p = sub.add_parser("unlink"); p.add_argument("--user", type=int, required=True)
    p = sub.add_parser("add-repo")
    p.add_argument("--tenant", type=int, required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--installation", type=int, required=True)
    p.add_argument("--base-branch", default="dev")
    p.add_argument("--prod-branch", default="main")

    args = ap.parse_args()
    db = SessionLocal()
    try:
        if args.cmd == "tenants":
            for t in db.query(Tenant).order_by(Tenant.id):
                repos = ", ".join(r.repo_full_name for r in t.repositories) or "-"
                print(f"#{t.id} {t.name} (plan={t.plan}) repos: {repos}")
        elif args.cmd == "list":
            _print_users(db, args.tenant)
        elif args.cmd == "add":
            tenant = db.get(Tenant, args.tenant)
            if not tenant:
                print("Tenant không tồn tại."); return
            u = create_user(db, tenant, role=UserRole(args.role), display_name=args.name,
                            platform=args.platform)
            db.commit()
            print(f"Tạo #{u.id} {u.role.value} '{args.name}' [{args.platform}] → /start {u.link_token}")
        elif args.cmd == "set-role":
            u = db.get(User, args.user)
            if not u:
                print("User không tồn tại."); return
            u.role = UserRole(args.role); db.commit()
            print(f"#{u.id} → {u.role.value}")
        elif args.cmd == "unlink":
            u = db.get(User, args.user)
            if not u:
                print("User không tồn tại."); return
            token = regenerate_link_token(db, u); db.commit()
            print(f"#{u.id} gỡ liên kết. Token mới → /start {token}")
        elif args.cmd == "add-repo":
            tenant = db.get(Tenant, args.tenant)
            if not tenant:
                print("Tenant không tồn tại."); return
            r = add_repository(db, tenant, args.repo, args.installation,
                               base_branch=args.base_branch, prod_branch=args.prod_branch)
            db.commit()
            print(f"Thêm repo #{r.id} {r.repo_full_name} vào tenant #{tenant.id}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
