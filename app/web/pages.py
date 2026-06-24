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
    head = _head("repos.title", "repos.subtitle", "/repo/add", "repos.add")
    if rows:
        body = "<div class='stack-sm'>" + "".join(_repo_card(r) for r in rows) + "</div>"
    else:
        body = _empty("repo", t("repos.empty.title"), t("repos.empty.desc"),
                      "/repo/add", t("repos.add"))
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


# ── Team (Người dùng + Workspace) ─────────────────────────────────────────────
_ROLES = ("employee", "manager", "admin")
_ROLE_BADGE = {"admin": "badge-info", "manager": "badge-success", "employee": "badge-muted"}


def _role_options(selected: str | None = None) -> str:
    return "".join(
        f"<option value='{r}'{' selected' if r == selected else ''}>{t('team.role.' + r)}</option>"
        for r in _ROLES)


def _team_user(u: dict, csrf: str) -> str:
    badge = _ROLE_BADGE.get(u["role"], "badge-muted")
    if u["linked"]:
        status = f"<span class='badge badge-success'>{t('team.linked')}</span>"
        action = (
            f"<form method='post' action='/users/unlink' style='flex:none' "
            f"onsubmit=\"return confirm('{esc(t('team.unlink_confirm'))}')\">"
            f"<input type='hidden' name='csrf' value='{esc(csrf)}'>"
            f"<input type='hidden' name='user_id' value='{u['id']}'>"
            f"<button class='btn btn-ghost' style='height:38px'>{t('team.unlink')}</button></form>")
        token = ""
    else:
        status = f"<span class='badge badge-warning'>{t('team.pending')}</span>"
        action = ""
        token = (f"<div class='hint' style='margin-top:8px'>{t('team.token')}: "
                 f"<span class='code'>{esc(u.get('token') or '—')}</span></div>") if u.get("token") else ""
    role_form = (
        f"<form method='post' action='/users/role' style='display:flex;gap:8px;flex:none'>"
        f"<input type='hidden' name='csrf' value='{esc(csrf)}'>"
        f"<input type='hidden' name='user_id' value='{u['id']}'>"
        f"<select class='input' name='role' style='height:38px;width:auto;padding-right:36px'>"
        f"{_role_options(u['role'])}</select>"
        f"<button class='btn btn-secondary' style='height:38px'>{t('team.save')}</button></form>")
    return f"""
      <div class='card card-tight'>
        <div class='card-row' style='justify-content:space-between;flex-wrap:wrap;gap:12px'>
          <div class='card-row' style='min-width:0'>
            <span class='ws-ico' style='width:38px;height:38px;flex:none'>{icon('users', 17)}</span>
            <div style='min-width:0'>
              <div style='font-weight:600;font-size:15px'>{esc(u.get('name') or '—')}</div>
              <div style='margin-top:4px;display:flex;gap:8px;align-items:center'>
                <span class='badge {badge}'>{esc(t('team.role.' + u['role']))}</span>{status}</div>
            </div>
          </div>
          <div class='card-row' style='gap:10px;flex:none'>{role_form}{action}</div>
        </div>{token}
      </div>"""


def _invite_form(tenant_id: int, csrf: str) -> str:
    return (
        f"<form method='post' action='/users/invite' class='card card-tight' "
        f"style='display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap;margin-top:12px'>"
        f"<input type='hidden' name='csrf' value='{esc(csrf)}'>"
        f"<input type='hidden' name='tenant_id' value='{tenant_id}'>"
        f"<div class='field' style='flex:1;min-width:200px;margin:0'>"
        f"<label>{t('team.invite_name')}</label>"
        f"<input class='input' name='name' required placeholder='{esc(t('team.invite_name_ph'))}'></div>"
        f"<div class='field' style='margin:0;flex:none'><label>{t('team.invite_role')}</label>"
        f"<select class='input' name='role' style='width:auto;padding-right:36px'>{_role_options('employee')}</select></div>"
        f"<button class='btn btn-primary' style='flex:none'>{icon('plus', 16)}{t('team.invite_btn')}</button>"
        f"</form>")


def _rename_form(tn: dict, csrf: str) -> str:
    return (
        f"<form method='post' action='/tenants/rename' style='display:flex;gap:10px;flex:none'>"
        f"<input type='hidden' name='csrf' value='{esc(csrf)}'>"
        f"<input type='hidden' name='tenant_id' value='{tn['id']}'>"
        f"<input class='input' name='name' value='{esc(tn['name'])}' maxlength='255' "
        f"aria-label='{esc(t('team.rename'))}' style='height:38px;width:200px'>"
        f"<button class='btn btn-secondary' style='height:38px'>{t('team.rename_btn')}</button></form>")


def _workspace_block(tn: dict, csrf: str) -> str:
    head = (
        f"<div class='card-row' style='justify-content:space-between;flex-wrap:wrap;gap:12px;margin:30px 0 14px'>"
        f"<div class='card-row'><span class='ws-ico' style='width:38px;height:38px;flex:none'>{icon('moon', 16)}</span>"
        f"<div><div style='font-weight:600;font-size:18px'>{esc(tn['name'])}</div>"
        f"<span class='badge badge-muted' style='margin-top:5px'>{t('team.plan')}: {esc(tn.get('plan') or 'free')}</span></div></div>"
        f"{_rename_form(tn, csrf)}</div>")
    if tn["users"]:
        users = "<div class='stack-sm'>" + "".join(_team_user(u, csrf) for u in tn["users"]) + "</div>"
    else:
        users = (f"<div class='card' style='text-align:center;padding:24px;color:var(--text-2)'>"
                 f"{t('team.no_users')}</div>")
    return head + users + _invite_form(tn["id"], csrf)


def team(user_name: str, workspaces: list[dict], csrf: str) -> str:
    head = _head("team.title", "team.subtitle")
    if workspaces:
        body = "".join(_workspace_block(tn, csrf) for tn in workspaces)
    else:
        body = _empty("users", t("team.empty.title"), t("team.empty.desc"), "/wizard", t("dash.new"))
    return shell(t("title.users"), active="users", user_name=user_name, body=head + body)


# ── Platform admin (super admin — read-only: mọi tenant + thống kê) ────────────
def _admin_tenant_row(tn: dict) -> str:
    owner = tn.get("owner") or "—"
    counts = (f"{tn.get('repos', 0)} · {tn.get('bots', 0)} · "
              f"{tn.get('users', 0)} · {tn.get('requests', 0)}")
    return f"""
      <div class='card card-tight card-row' style='justify-content:space-between;gap:12px;flex-wrap:wrap'>
        <div class='card-row' style='min-width:0'>
          <span class='ws-ico' style='width:40px;height:40px;flex:none'>{icon('moon', 18)}</span>
          <div style='min-width:0'>
            <div style='font-weight:600;font-size:15px'>{esc(tn.get('name') or '—')}</div>
            <div class='hint' style='margin:2px 0 0;display:flex;gap:8px;align-items:center'>
              {icon('users', 13)}{esc(owner)}</div>
          </div>
        </div>
        <div class='card-row' style='gap:14px;flex:none;flex-wrap:wrap'>
          <span class='hint' style='margin:0'>{t('admin.col.counts')}: <b>{esc(counts)}</b></span>
          <span class='badge badge-muted'>{esc(tn.get('platform') or '—')}</span>
          <span class='badge badge-info'>{t('admin.col.plan')}: {esc(tn.get('plan') or 'free')}</span>
          <span class='hint' style='margin:0'>{esc(tn.get('created') or '')}</span>
        </div>
      </div>"""


def admin(user_name: str, stats: dict, tenants: list[dict]) -> str:
    cells = [
        ("layers", "admin.stat.tenants", stats.get("tenants", 0)),
        ("bot", "admin.stat.bots", stats.get("bots", 0)),
        ("repo", "admin.stat.repos", stats.get("repos", 0)),
        ("users", "admin.stat.users", stats.get("users", 0)),
        ("requests", "admin.stat.requests", stats.get("requests", 0)),
        ("activity", "admin.stat.active", stats.get("active", 0)),
    ]
    grid = "<div class='stats'>" + "".join(
        f"<div class='card stat'><div class='stat-num'>{int(n)}</div>"
        f"<div class='stat-lbl'>{icon(ico, 15)}{t(key)}</div></div>"
        for ico, key, n in cells
    ) + "</div>"
    if tenants:
        body = (f"<h2 class='section-title' style='margin:6px 0 14px'>{t('admin.tenants')}</h2>"
                "<div class='stack-sm'>" + "".join(_admin_tenant_row(tn) for tn in tenants) + "</div>")
    else:
        body = _empty("layers", t("admin.empty.title"), t("admin.empty.desc"))
    head = _head("admin.title", "admin.subtitle")
    return shell(t("title.admin"), active="admin", user_name=user_name, body=head + grid + body)
