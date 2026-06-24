"""Các trang app-shell (sidebar) ngoài wizard: overview, repositories, requests,
activity, settings. Render chuỗi HTML như templates.py (không Jinja2); design system &
helper (`shell`, `icon`, `status_dot`) ở app/web/styles.py. `esc()` chống XSS mọi giá trị
động. Các hàm nhận dict thuần (route đã chuẩn hoá datetime → chuỗi) để template không
chạm DB.
"""
from __future__ import annotations

from html import escape as esc

from app.web.i18n import t
from app.web.styles import icon, shell, status_dot


def _empty(ico: str, title: str, desc: str, cta_href: str = "", cta: str = "") -> str:
    btn = (f"<a class='btn btn-primary' href='{esc(cta_href)}'>{icon('plus', 16)}{esc(cta)}</a>"
           if cta else "")
    return f"""
      <div class='card empty'>
        <div class='e-ico'>{icon(ico, 26)}</div>
        <h2 class='section-title'>{esc(title)}</h2>
        <p class='muted' style='max-width:380px;margin:8px auto 20px'>{esc(desc)}</p>
        {btn}
      </div>"""


def _head(title_key: str, sub_key: str, cta_href: str = "", cta_key: str = "") -> str:
    btn = (f"<a class='btn btn-primary' href='{esc(cta_href)}'>{icon('plus', 16)}{t(cta_key)}</a>"
           if cta_key else "")
    return f"""
      <div class='page-head'>
        <div><h1 class='page-title'>{t(title_key)}</h1>
          <p class='muted' style='margin-top:4px'>{t(sub_key)}</p></div>
        {btn}
      </div>"""


def _status_chip(status: str | None) -> str:
    label = esc((status or "").replace("_", " ") or "—")
    return f"<span class='status'><span class='dot {status_dot(status)}'></span>{label}</span>"


def _req_row(r: dict) -> str:
    pr = ""
    if r.get("pr_url"):
        num = f"#{esc(str(r['pr_number']))} " if r.get("pr_number") else ""
        pr = (f"<a class='hint' style='margin:0' target='_blank' rel='noopener' "
              f"href='{esc(r['pr_url'])}'>{icon('repo', 13)}{num}{t('reqs.view_pr')}</a>")
    meta = f"{icon('repo', 13)}{esc(r.get('repo') or '—')}"
    if r.get("updated"):
        meta += f" · {esc(r['updated'])}"
    return f"""
      <div class='card card-tight card-row' style='justify-content:space-between'>
        <div style='min-width:0'>
          <div style='font-weight:600;font-size:15px'>{esc(r.get('title') or '—')}</div>
          <div class='hint' style='margin:4px 0 0;display:flex;gap:8px;align-items:center'>{meta}</div>
        </div>
        <div style='display:flex;align-items:center;gap:16px;flex:none'>{pr}{_status_chip(r.get('status'))}</div>
      </div>"""


# ── Overview (Dashboard) ──────────────────────────────────────────────────────
def overview(user_name: str, stats: dict, recent: list[dict]) -> str:
    cells = [
        ("bot", "over.stat.bots", stats.get("bots", 0)),
        ("repo", "over.stat.repos", stats.get("repos", 0)),
        ("requests", "over.stat.requests", stats.get("requests", 0)),
        ("activity", "over.stat.active", stats.get("active", 0)),
    ]
    grid = "<div class='stats'>" + "".join(
        f"<div class='card stat'><div class='stat-num'>{int(n)}</div>"
        f"<div class='stat-lbl'>{icon(ico, 15)}{t(key)}</div></div>"
        for ico, key, n in cells
    ) + "</div>"
    if recent:
        body = (f"<h2 class='section-title' style='margin-bottom:14px'>{t('over.recent')}</h2>"
                "<div class='stack-sm'>" + "".join(_req_row(r) for r in recent) + "</div>")
    else:
        body = (f"<div class='card' style='text-align:center;padding:32px;color:var(--text-2)'>"
                f"{t('over.recent.empty')}</div>")
    head = _head("over.title", "over.subtitle", "/wizard", "dash.new")
    return shell(t("title.dashboard"), active="dashboard", user_name=user_name,
                 body=head + grid + body)


# ── Repositories ──────────────────────────────────────────────────────────────
def _repo_card(r: dict) -> str:
    installed = r.get("installed")
    badge = (f"<span class='badge badge-success'>{t('repos.installed')}</span>" if installed
             else f"<span class='badge badge-warning'>{t('repos.not_installed')}</span>")
    branches = f"{esc(r.get('base') or 'dev')} → {esc(r.get('prod') or 'main')}"
    return f"""
      <div class='card card-tight card-row' style='justify-content:space-between'>
        <div class='card-row' style='min-width:0'>
          <span class='ws-ico' style='width:40px;height:40px'>{icon('repo', 20)}</span>
          <div style='min-width:0'>
            <div style='font-weight:600;font-size:15px'>{esc(r.get('full_name') or '—')}</div>
            <div class='hint' style='margin:2px 0 0'>{branches} · {t('repos.bots').replace('{n}', str(r.get('bots', 0)))}</div>
          </div>
        </div>
        <div style='flex:none'>{badge}</div>
      </div>"""


def repositories(user_name: str, rows: list[dict]) -> str:
    head = _head("repos.title", "repos.subtitle", "/wizard", "repos.connect")
    if rows:
        body = "<div class='stack-sm'>" + "".join(_repo_card(r) for r in rows) + "</div>"
    else:
        body = _empty("repo", t("repos.empty.title"), t("repos.empty.desc"),
                      "/wizard", t("repos.connect"))
    return shell(t("title.repositories"), active="repo", user_name=user_name, body=head + body)


# ── Requests ──────────────────────────────────────────────────────────────────
def requests(user_name: str, rows: list[dict]) -> str:
    head = _head("reqs.title", "reqs.subtitle")
    if rows:
        body = "<div class='stack-sm'>" + "".join(_req_row(r) for r in rows) + "</div>"
    else:
        body = _empty("requests", t("reqs.empty.title"), t("reqs.empty.desc"))
    return shell(t("title.requests"), active="requests", user_name=user_name, body=head + body)


# ── Activity ──────────────────────────────────────────────────────────────────
def _event_row(e: dict) -> str:
    ico = "send" if e.get("direction") == "out" else "requests"
    kind = esc((e.get("kind") or "").replace("_", " "))
    when = f" · {esc(e['when'])}" if e.get("when") else ""
    return f"""
      <div class='card card-tight card-row'>
        <span class='ws-ico' style='width:36px;height:36px;flex:none'>{icon(ico, 16)}</span>
        <div style='min-width:0'>
          <div style='font-weight:600;font-size:14px'>{esc(e.get('title') or '—')}</div>
          <div class='hint' style='margin:2px 0 0'>{kind}{when}</div>
        </div>
      </div>"""


def activity(user_name: str, rows: list[dict]) -> str:
    head = _head("act.title", "act.subtitle")
    if rows:
        body = "<div class='stack-sm'>" + "".join(_event_row(e) for e in rows) + "</div>"
    else:
        body = _empty("activity", t("act.empty.title"), t("act.empty.desc"))
    return shell(t("title.activity"), active="activity", user_name=user_name, body=head + body)


# ── Settings ──────────────────────────────────────────────────────────────────
def _kv(label: str, value: str) -> str:
    return (f"<div class='card-row' style='justify-content:space-between;padding:14px 0'>"
            f"<span class='muted'>{esc(label)}</span>"
            f"<span style='font-weight:600'>{esc(value)}</span></div>")


def settings(user_name: str, account: dict, tenants: list[dict]) -> str:
    head = _head("set.title", "set.subtitle")
    acct = (f"<div class='card'><h2 class='section-title'>{t('set.account')}</h2>"
            f"<div class='stack-sm' style='margin-top:8px'>"
            f"{_kv(t('set.github'), '@' + (account.get('login') or '—'))}"
            f"{_kv(t('set.name'), account.get('name') or '—')}"
            f"</div></div>")
    if tenants:
        items = "".join(
            f"<div class='card card-tight card-row' style='justify-content:space-between'>"
            f"<div class='card-row'><span class='ws-ico' style='width:36px;height:36px'>"
            f"{icon('moon', 15)}</span><span style='font-weight:600'>{esc(w.get('name') or '—')}</span></div>"
            f"<span class='badge badge-muted'>{t('set.plan')}: {esc(w.get('plan') or 'free')}</span></div>"
            for w in tenants
        )
        ws = (f"<h2 class='section-title' style='margin:28px 0 14px'>{t('set.workspaces')}</h2>"
              f"<div class='stack-sm'>{items}</div>")
    else:
        ws = (f"<h2 class='section-title' style='margin:28px 0 14px'>{t('set.workspaces')}</h2>"
              f"<div class='card' style='text-align:center;padding:28px;color:var(--text-2)'>"
              f"{t('set.empty')}</div>")
    danger = (f"<h2 class='section-title' style='margin:28px 0 14px'>{t('set.danger')}</h2>"
              f"<div class='card card-row' style='justify-content:space-between'>"
              f"<span class='muted'>{t('set.signout.desc')}</span>"
              f"<a class='btn btn-secondary' href='/logout'>{icon('logout', 16)}{t('common.logout')}</a></div>")
    return shell(t("title.settings"), active="settings", user_name=user_name,
                 body=head + acct + ws + danger)
