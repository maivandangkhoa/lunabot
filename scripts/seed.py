"""Seed thủ công 1 tenant + repo + users (MVP, chạy 1 lần để onboard).

Dùng:
    python -m scripts.seed --tenant "Acme" --repo acme/widgets --installation 12345 \\
        --manager "Alice" --employee "Bob"

In ra link_token cho từng user → gửi để họ /start <token> trên Telegram.
"""
from __future__ import annotations

import argparse

from app.db import SessionLocal
from app.models import UserRole
from app.onboarding import add_repository, create_tenant, create_user


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--repo", required=True, help="owner/repo")
    ap.add_argument("--installation", type=int, required=True, help="gh_installation_id")
    ap.add_argument("--base-branch", default="dev")
    ap.add_argument("--prod-branch", default="main")
    ap.add_argument("--manager", action="append", default=[], help="tên manager (lặp lại được)")
    ap.add_argument("--employee", action="append", default=[], help="tên employee (lặp lại được)")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        tenant = create_tenant(db, args.tenant)
        add_repository(
            db, tenant, args.repo, args.installation,
            base_branch=args.base_branch, prod_branch=args.prod_branch,
        )
        print(f"Tenant #{tenant.id} '{tenant.name}' + repo {args.repo}")
        for name in args.manager:
            u = create_user(db, tenant, role=UserRole.MANAGER, display_name=name)
            print(f"  manager  {name}: /start {u.link_token}")
        for name in args.employee:
            u = create_user(db, tenant, role=UserRole.EMPLOYEE, display_name=name)
            print(f"  employee {name}: /start {u.link_token}")
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()
