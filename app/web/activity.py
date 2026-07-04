"""Trang Activity (/activity): dòng sự kiện + bộ lọc (thời gian / loại sự kiện / trạng thái
request) và xoá log theo đúng bộ lọc đang xem.

`request_events` chỉ là nhật ký hiển thị/audit — KHÔNG được FSM hay `--resume` đọc lại
(state ở `Request.status`, ngữ cảnh Claude ở `claude_session_id`). Vì vậy xoá an toàn về
mặt nghiệp vụ: chỉ mất lịch sử hiển thị, không ảnh hưởng bot/request đang chạy.

Tách khỏi routes.py để giữ mỗi file ≤500 LOC; tái dùng _auth/_csrf/_form/_tenants/_fmt.
"""
from __future__ import annotations

import hmac
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import EventKind, Request as MaintRequest, RequestEvent, RequestStatus
from app.web import pages
from app.web.routes import _auth, _csrf, _fmt, _form, _tenants

router = APIRouter(tags=["web-activity"])

# bộ lọc thời gian → số giờ lùi về trước (None = mọi lúc)
_TIME_WINDOWS = {"all": None, "24h": 24, "7d": 24 * 7, "30d": 24 * 30}
_LIMIT = 80  # giới hạn dòng hiển thị để trang không phình


def _parse_filters(time: str, kind: str, status: str) -> dict:
    """Chuẩn hoá tham số lọc về giá trị hợp lệ (rơi về 'all' nếu lạ — chống injection)."""
    return {
        "time": time if time in _TIME_WINDOWS else "all",
        "kind": kind if kind in EventKind._value2member_map_ else "all",
        "status": status if status in RequestStatus._value2member_map_ else "all",
    }


def _conditions(ids: list[int], f: dict) -> list:
    """Điều kiện WHERE dùng chung cho cả hiển thị lẫn xoá (đảm bảo xoá đúng cái đang xem)."""
    conds = [MaintRequest.tenant_id.in_(ids)]
    if f["kind"] != "all":
        conds.append(RequestEvent.kind == EventKind(f["kind"]))
    if f["status"] != "all":
        conds.append(MaintRequest.status == RequestStatus(f["status"]))
    hrs = _TIME_WINDOWS.get(f["time"])
    if hrs:
        conds.append(RequestEvent.created_at >= datetime.now(timezone.utc) - timedelta(hours=hrs))
    return conds


def _redirect_with_filters(f: dict) -> str:
    qs = urlencode({k: v for k, v in f.items() if v != "all"})
    return "/activity" + (f"?{qs}" if qs else "")


@router.get("/activity", response_class=HTMLResponse)
async def activity(request: Request, db: Session = Depends(get_db),
                   time: str = "all", kind: str = "all", status: str = "all"):
    data = _auth(request, db)
    if not data:
        return RedirectResponse("/", status_code=303)
    f = _parse_filters(time, kind, status)
    ids = [t.id for t in _tenants(db, data)]
    rows: list[dict] = []
    if ids:
        evs = db.execute(
            select(RequestEvent, MaintRequest.title)
            .join(MaintRequest, RequestEvent.request_id == MaintRequest.id)
            .where(*_conditions(ids, f))
            .order_by(RequestEvent.created_at.desc()).limit(_LIMIT)
        ).all()
        rows = [{"title": title, "kind": ev.kind.value, "direction": ev.direction.value,
                 "payload": ev.payload_json or {}, "when": _fmt(ev.created_at)}
                for ev, title in evs]
    csrf = _csrf(data, get_settings())
    return HTMLResponse(pages.activity(data.get("name") or data["login"], rows, f, csrf))


@router.post("/activity/clear")
async def clear(request: Request, db: Session = Depends(get_db)):
    """Xoá các sự kiện khớp đúng bộ lọc đang xem (time/kind/status) trong workspace của user."""
    data = _auth(request)
    if not data:
        return RedirectResponse("/", status_code=303)
    form = await _form(request)
    if not hmac.compare_digest(form.get("csrf", ""), _csrf(data)):
        return RedirectResponse("/activity", status_code=303)
    f = _parse_filters(form.get("time", "all"), form.get("kind", "all"),
                       form.get("status", "all"))
    ids = [t.id for t in _tenants(db, data)]
    if ids:
        # Xoá theo id qua subquery để áp được điều kiện join (status nằm ở bảng requests).
        sub = (select(RequestEvent.id)
               .join(MaintRequest, RequestEvent.request_id == MaintRequest.id)
               .where(*_conditions(ids, f)))
        db.execute(delete(RequestEvent).where(RequestEvent.id.in_(sub))
                   .execution_options(synchronize_session=False))
        db.commit()
    return RedirectResponse(_redirect_with_filters(f), status_code=303)
