"""Trang Usage — đo lượng dùng Claude (token / chi phí quy đổi API) từ `usage_records`.

Hai góc nhìn:
- `/usage` (chủ workspace): tổng chi phí/token/lượt chạy trong cửa sổ thời gian, breakdown
  theo phase và theo request — dữ liệu nền để định giá (cost trung bình 1 request).
- `/admin/usage` (super admin): tổng TOÀN HỆ THỐNG + bảng chia theo tenant (% share) + so
  với quota subscription (cửa sổ 5h/7 ngày, ngưỡng cấu hình `SUB_QUOTA_USD_5H`/`_WEEK` —
  calibrate từ các lần `status="limit"`).

`cost_usd` là chi phí QUY ĐỔI API do CLI báo (kể cả khi chạy OAuth subscription) — đơn vị
chuẩn hoá mọi model/cache mix, dùng trực tiếp cho việc tính tiền. Route + render gộp 1 file
(pattern activity.py) để routes/pages.py không phình quá 500 LOC.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape as esc

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Request as MaintRequest, Tenant, UsageRecord
from app.web.i18n import t
from app.web.pages import _empty, _head
from app.web.routes import _auth, _tenants, is_super_admin
from app.web.styles import icon, shell

router = APIRouter(tags=["web-usage"])

# bộ lọc thời gian → số giờ lùi về trước (None = mọi lúc). Mặc định 30d (chu kỳ tính tiền).
_WINDOWS = {"24h": 24, "7d": 24 * 7, "30d": 24 * 30, "all": None}
_TOP_REQUESTS = 20

# Tổng token vào (kể cả cache — cache_read rẻ hơn nhưng vẫn là lưu lượng).
_TOK_IN = (UsageRecord.input_tokens + UsageRecord.cache_read_tokens
           + UsageRecord.cache_creation_tokens)
_COST = func.coalesce(func.sum(UsageRecord.cost_usd), 0)
_LIMIT_HITS = func.coalesce(
    func.sum(case((UsageRecord.status == "limit", 1), else_=0)), 0)


def _window(time: str) -> str:
    return time if time in _WINDOWS else "30d"


def _since(window: str) -> datetime | None:
    hrs = _WINDOWS[window]
    return datetime.now(timezone.utc) - timedelta(hours=hrs) if hrs else None


def _conds(tenant_ids: list[int] | None, since: datetime | None) -> list:
    conds = []
    if tenant_ids is not None:
        conds.append(UsageRecord.tenant_id.in_(tenant_ids))
    if since is not None:
        conds.append(UsageRecord.created_at >= since)
    return conds


# ---------------- aggregation ----------------
def _totals(db: Session, tenant_ids: list[int] | None, since: datetime | None) -> dict:
    row = db.execute(
        select(_COST, func.coalesce(func.sum(_TOK_IN), 0),
               func.coalesce(func.sum(UsageRecord.output_tokens), 0),
               func.count(), _LIMIT_HITS)
        .where(*_conds(tenant_ids, since))
    ).one()
    return {"cost": float(row[0] or 0), "tok_in": int(row[1] or 0),
            "tok_out": int(row[2] or 0), "runs": int(row[3] or 0),
            "limit_hits": int(row[4] or 0)}


def _by_phase(db: Session, tenant_ids: list[int] | None, since: datetime | None) -> list[dict]:
    rows = db.execute(
        select(UsageRecord.phase, func.count(), _COST,
               func.coalesce(func.sum(_TOK_IN), 0),
               func.coalesce(func.sum(UsageRecord.output_tokens), 0))
        .where(*_conds(tenant_ids, since))
        .group_by(UsageRecord.phase).order_by(_COST.desc())
    ).all()
    return [{"phase": p, "runs": int(n), "cost": float(c or 0),
             "tok_in": int(ti or 0), "tok_out": int(to or 0)}
            for p, n, c, ti, to in rows]


def _by_request(db: Session, tenant_ids: list[int], since: datetime | None) -> list[dict]:
    rows = db.execute(
        select(MaintRequest.id, MaintRequest.title, func.count(), _COST)
        .join(MaintRequest, UsageRecord.request_id == MaintRequest.id)
        .where(*_conds(tenant_ids, since))
        .group_by(MaintRequest.id, MaintRequest.title)
        .order_by(_COST.desc()).limit(_TOP_REQUESTS)
    ).all()
    return [{"id": rid, "title": title, "runs": int(n), "cost": float(c or 0)}
            for rid, title, n, c in rows]


def _by_tenant(db: Session, since: datetime | None) -> list[dict]:
    rows = db.execute(
        select(Tenant.id, Tenant.name, func.count(), _COST,
               func.coalesce(func.sum(_TOK_IN), 0),
               func.coalesce(func.sum(UsageRecord.output_tokens), 0), _LIMIT_HITS)
        .join(UsageRecord, UsageRecord.tenant_id == Tenant.id)
        .where(*_conds(None, since))
        .group_by(Tenant.id, Tenant.name).order_by(_COST.desc())
    ).all()
    out = [{"id": tid, "name": name, "runs": int(n), "cost": float(c or 0),
            "tok_in": int(ti or 0), "tok_out": int(to or 0), "limit_hits": int(lh or 0)}
           for tid, name, n, c, ti, to, lh in rows]
    total = sum(r["cost"] for r in out) or 0.0
    for r in out:
        r["share"] = (r["cost"] / total * 100) if total > 0 else 0.0
    return out


# ---------------- render helpers ----------------
def fmt_cost(v: float | None) -> str:
    v = float(v or 0)
    return f"${v:,.2f}" if v >= 0.01 or v == 0 else f"${v:.4f}"


def fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def _stat_cells(tot: dict) -> str:
    cells = [
        ("usage", "usage.stat.cost", fmt_cost(tot["cost"])),
        ("activity", "usage.stat.runs", str(tot["runs"])),
        ("requests", "usage.stat.tok_in", fmt_tokens(tot["tok_in"])),
        ("send", "usage.stat.tok_out", fmt_tokens(tot["tok_out"])),
        ("alert", "usage.stat.limit_hits", str(tot["limit_hits"])),
    ]
    return "<div class='stats'>" + "".join(
        f"<div class='card stat'><div class='stat-num'>{esc(v)}</div>"
        f"<div class='stat-lbl'>{icon(ico, 15)}{t(key)}</div></div>"
        for ico, key, v in cells) + "</div>"


def _time_bar(action: str, window: str) -> str:
    opts = "".join(
        f"<option value='{v}'{' selected' if v == window else ''}>"
        f"{t('act.filter.all') if v == 'all' else t('act.filter.time.' + v)}</option>"
        for v in _WINDOWS)
    return (f"<form method='get' action='{action}' style='margin-bottom:16px'>"
            f"<select class='input' name='time' onchange='this.form.submit()' "
            f"style='height:38px;width:auto;padding-right:36px'>{opts}</select>"
            f"<noscript><button class='btn btn-secondary' style='height:38px'>OK</button>"
            f"</noscript></form>")


def _table(headers: list[str], rows: list[str]) -> str:
    head = "".join(f"<th style='text-align:left;padding:10px 12px;color:var(--text-2);"
                   f"font-size:12px;font-weight:600'>{esc(h)}</th>" for h in headers)
    return (f"<div class='card card-tight' style='padding:0;overflow-x:auto'>"
            f"<table style='width:100%;border-collapse:collapse;font-size:14px'>"
            f"<thead><tr style='border-bottom:1px solid var(--border)'>{head}</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>")


def _td(val: str, *, bold: bool = False) -> str:
    w = "600" if bold else "400"
    return (f"<td style='padding:10px 12px;border-top:1px solid var(--border);"
            f"font-weight:{w}'>{val}</td>")


def _note() -> str:
    return (f"<p class='hint' style='margin:0 0 16px'>{icon('info', 13)} "
            f"{t('usage.note')}</p>")


def _phase_section(phases: list[dict]) -> str:
    if not phases:
        return ""
    rows = ["<tr>" + _td(esc(p["phase"]), bold=True) + _td(str(p["runs"]))
            + _td(fmt_cost(p["cost"])) + _td(fmt_tokens(p["tok_in"]))
            + _td(fmt_tokens(p["tok_out"])) + "</tr>" for p in phases]
    return (f"<h2 class='section-title' style='margin:24px 0 12px'>{t('usage.by_phase')}</h2>"
            + _table([t("usage.col.phase"), t("usage.col.runs"), t("usage.col.cost"),
                      t("usage.col.tok_in"), t("usage.col.tok_out")], rows))


def _request_section(reqs: list[dict]) -> str:
    if not reqs:
        return ""
    rows = ["<tr>" + _td(f"#{r['id']} " + esc((r["title"] or "")[:80]), bold=True)
            + _td(str(r["runs"])) + _td(fmt_cost(r["cost"])) + "</tr>" for r in reqs]
    return (f"<h2 class='section-title' style='margin:24px 0 12px'>{t('usage.by_request')}</h2>"
            + _table([t("usage.col.request"), t("usage.col.runs"), t("usage.col.cost")], rows))


def _quota_bar(label: str, spent: float, quota: float | None) -> str:
    """1 dòng so quota: đã dùng / trần (bar %). Không cấu hình trần → chỉ hiện số đã dùng."""
    if not quota:
        detail = f"{fmt_cost(spent)} · {t('admusage.no_quota')}"
        bar = ""
    else:
        pct = min(spent / quota * 100, 100.0)
        color = "var(--danger)" if pct >= 90 else ("var(--warning)" if pct >= 70
                                                   else "var(--success)")
        detail = f"{fmt_cost(spent)} / {fmt_cost(quota)} ({pct:.0f}%)"
        bar = (f"<div style='background:var(--border);border-radius:99px;height:8px;"
               f"overflow:hidden;margin-top:8px'>"
               f"<div style='width:{pct:.1f}%;height:100%;background:{color}'></div></div>")
    return (f"<div class='card card-tight'><div class='card-row' "
            f"style='justify-content:space-between'><span class='muted'>{esc(label)}</span>"
            f"<span style='font-weight:600'>{detail}</span></div>{bar}</div>")


# ---------------- routes ----------------
@router.get("/usage", response_class=HTMLResponse)
async def usage_page(request: Request, db: Session = Depends(get_db), time: str = "30d"):
    data = _auth(request, db)
    if not data:
        return RedirectResponse("/", status_code=303)
    window = _window(time)
    since = _since(window)
    ids = [tn.id for tn in _tenants(db, data)]
    if not ids:
        body = _empty("usage", t("usage.empty.title"), t("usage.empty.desc"))
        return HTMLResponse(shell(t("title.usage"), active="usage",
                                  user_name=data.get("name") or data["login"],
                                  body=_head("usage.title", "usage.subtitle") + body))
    tot = _totals(db, ids, since)
    body = _head("usage.title", "usage.subtitle") + _note() + _time_bar("/usage", window)
    if tot["runs"] == 0:
        body += _empty("usage", t("usage.empty.title"), t("usage.empty.desc"))
    else:
        body += (_stat_cells(tot) + _phase_section(_by_phase(db, ids, since))
                 + _request_section(_by_request(db, ids, since)))
    return HTMLResponse(shell(t("title.usage"), active="usage",
                              user_name=data.get("name") or data["login"], body=body))


@router.get("/admin/usage", response_class=HTMLResponse)
async def admin_usage(request: Request, db: Session = Depends(get_db), time: str = "30d"):
    data = _auth(request, db)
    if not data:
        return RedirectResponse("/", status_code=303)
    if not is_super_admin(db, data):
        return RedirectResponse("/dashboard", status_code=303)
    s = get_settings()
    window = _window(time)
    since = _since(window)

    # So quota subscription theo cửa sổ TRƯỢT cố định (5h + 7 ngày) — độc lập bộ lọc xem.
    now = datetime.now(timezone.utc)
    spent_5h = _totals(db, None, now - timedelta(hours=5))["cost"]
    spent_week = _totals(db, None, now - timedelta(days=7))["cost"]
    quota = (f"<h2 class='section-title' style='margin:24px 0 12px'>{t('admusage.quota')}</h2>"
             f"<div class='stack-sm'>"
             + _quota_bar(t("admusage.quota_5h"), spent_5h, s.sub_quota_usd_5h)
             + _quota_bar(t("admusage.quota_week"), spent_week, s.sub_quota_usd_week)
             + "</div>")

    tot = _totals(db, None, since)
    tenants = _by_tenant(db, since)
    rows = ["<tr>" + _td(esc(r["name"]), bold=True) + _td(str(r["runs"]))
            + _td(fmt_cost(r["cost"])) + _td(f"{r['share']:.1f}%")
            + _td(fmt_tokens(r["tok_in"])) + _td(fmt_tokens(r["tok_out"]))
            + _td(str(r["limit_hits"])) + "</tr>" for r in tenants]
    table = (_table([t("admusage.col.tenant"), t("usage.col.runs"), t("usage.col.cost"),
                     t("admusage.col.share"), t("usage.col.tok_in"), t("usage.col.tok_out"),
                     t("usage.stat.limit_hits")], rows)
             if tenants else _empty("usage", t("usage.empty.title"), t("usage.empty.desc")))
    body = (_head("admusage.title", "admusage.subtitle") + _note()
            + _time_bar("/admin/usage", window) + _stat_cells(tot) + quota
            + f"<h2 class='section-title' style='margin:24px 0 12px'>{t('admusage.tenants')}</h2>"
            + table)
    return HTMLResponse(shell(t("title.admin_usage"), active="admin_usage",
                              user_name=data.get("name") or data["login"], body=body))
