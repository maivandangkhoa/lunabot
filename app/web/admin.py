"""Trang Platform admin (/admin) — super admin xem TOÀN BỘ tenant + thống kê hệ thống.

Khác mọi trang khác (lọc theo owner đăng nhập): trang này read-only, không lọc theo
owner — chỉ super admin (bảng platform_admins, khớp github_id phiên) mới vào được; người
thường bị đẩy về /dashboard. Tách khỏi routes.py để giữ mỗi file ≤500 LOC; dùng lại
helper phiên (_auth, is_super_admin) từ routes.
"""
from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.claude_runner import MODEL_IDS
from app.db import get_db
from app.models import Bot, Repository, Request as MaintRequest, Tenant, User, UserRole
from app.web import pages
from app.web.routes import _auth, _csrf, _fmt, _form, is_super_admin

router = APIRouter(tags=["web-admin"])

# Trạng thái request "đang xử lý" (chưa kết thúc) — đếm cho thẻ thống kê.
_ACTIVE = {"new", "analyzing", "clarifying", "plan_review", "executing", "verify",
           "merged_dev", "await_manager"}


def _counts(db: Session, model) -> dict[int, int]:
    """{tenant_id: số dòng} cho 1 bảng có cột tenant_id — 1 query group-by, tránh N+1."""
    rows = db.execute(
        select(model.tenant_id, func.count()).group_by(model.tenant_id)
    ).all()
    return {tid: n for tid, n in rows}


def _platforms_by_tenant(db: Session) -> dict[int, list[str]]:
    """{tenant_id: [kênh chat thực]} — suy từ Bot.platform (nguồn sự thật), distinct + đã sort.
    1 query duy nhất. Thay cho field chết Tenant.chat_platform (luôn = 'telegram')."""
    out: dict[int, set[str]] = {}
    rows = db.execute(select(Bot.tenant_id, Bot.platform).distinct()).all()
    for tid, pf in rows:
        out.setdefault(tid, set()).add(pf)
    return {tid: sorted(pfs) for tid, pfs in out.items()}


def _admins_by_tenant(db: Session) -> dict[int, list[dict]]:
    """{tenant_id: [admin/manager]} — người quản trị THẬT (role), khác owner (web). ADMIN trước.
    1 query duy nhất rồi gom Python (tránh N+1 theo từng tenant)."""
    out: dict[int, list[dict]] = {}
    rows = db.scalars(
        select(User).where(User.role.in_([UserRole.ADMIN, UserRole.MANAGER]))
        .order_by(User.role, User.id)
    ).all()
    for u in rows:
        out.setdefault(u.tenant_id, []).append({
            "name": u.display_name or "—", "role": u.role.value,
            "platform": u.platform, "linked": u.platform_user_id is not None,
        })
    return out


@router.get("/admin", response_class=HTMLResponse)
async def admin_home(request: Request, db: Session = Depends(get_db)):
    data = _auth(request, db)
    if not data:
        return RedirectResponse("/", status_code=303)
    if not is_super_admin(db, data):
        return RedirectResponse("/dashboard", status_code=303)

    repos = _counts(db, Repository)
    bots = _counts(db, Bot)
    users = _counts(db, User)
    reqs = _counts(db, MaintRequest)
    admins = _admins_by_tenant(db)
    platforms = _platforms_by_tenant(db)
    n_active = db.scalar(
        select(func.count()).select_from(MaintRequest)
        .where(MaintRequest.status.in_(_ACTIVE))
    ) or 0

    tenants = []
    for tn in db.scalars(select(Tenant).order_by(Tenant.created_at.desc())).all():
        tenants.append({
            "name": tn.name,
            "owner": ("@" + tn.owner_github_login) if tn.owner_github_login else "—",
            "plan": tn.plan, "platforms": platforms.get(tn.id, []),
            "repos": repos.get(tn.id, 0), "bots": bots.get(tn.id, 0),
            "users": users.get(tn.id, 0), "requests": reqs.get(tn.id, 0),
            "created": _fmt(tn.created_at), "admins": admins.get(tn.id, []),
            "id": tn.id,
            "model": (tn.settings_json or {}).get("claude_model") or "",
        })

    stats = {
        "tenants": len(tenants),
        "bots": sum(bots.values()), "repos": sum(repos.values()),
        "users": sum(users.values()), "requests": sum(reqs.values()),
        "active": n_active,
    }
    return HTMLResponse(pages.admin(
        data.get("name") or data["login"], stats, tenants, _csrf(data)))


@router.post("/admin/tenant/model")
async def admin_set_model(request: Request, db: Session = Depends(get_db)):
    """Super admin ghim model Claude cho 1 tenant (lưu vào settings_json['claude_model']).
    Guard: phiên hợp lệ + super admin + CSRF. Model phải nằm trong MODEL_IDS (rỗng = default)."""
    data = _auth(request, db)
    if not data or not is_super_admin(db, data):
        return RedirectResponse("/dashboard", status_code=303)
    form = await _form(request)
    if not hmac.compare_digest(form.get("csrf", ""), _csrf(data)):
        return RedirectResponse("/admin", status_code=303)
    model = (form.get("model") or "").strip()
    try:
        tid = int(form.get("tenant_id"))
    except (TypeError, ValueError):
        tid = None
    tn = db.get(Tenant, tid) if tid is not None else None
    if tn is not None and model in MODEL_IDS:
        # settings_json là JSONB mutate-in-place → gán lại dict mới để SQLAlchemy phát hiện.
        tn.settings_json = {**(tn.settings_json or {}), "claude_model": model}
        db.commit()
    return RedirectResponse("/admin", status_code=303)
