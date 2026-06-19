"""Web wizard routes — đăng nhập GitHub OAuth → chọn repo → tạo bot (provision) → hướng dẫn.

Cố tình KHÔNG thêm dep: form parse thủ công (urllib) thay python-multipart; cookie ký HMAC
(app/web/session.py) thay itsdangerous; HTML render chuỗi (app/web/templates.py) thay Jinja2.
"""
from __future__ import annotations

import logging
import secrets
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.github_oauth import GitHubOAuth, GitHubOAuthError
from app.models import Bot, Repository, Tenant
from app.provisioning import ProvisioningError, provision
from app.web import session as sess
from app.web import templates as tpl

log = logging.getLogger("luna.web")
router = APIRouter(tags=["web"])


# ----- helpers -----
def _enabled(s) -> bool:
    return bool(s.public_base_url and s.github_oauth_client_id
                and s.github_oauth_client_secret and s.github_app_slug)


def _redirect_uri(s) -> str:
    return f"{s.public_base_url.rstrip('/')}/oauth/github/callback"


def _read_session(request: Request, s) -> dict | None:
    return sess.loads(request.cookies.get(sess.COOKIE_NAME), s.web_session_secret)


def _attach_session(resp, data: dict, s) -> None:
    resp.set_cookie(sess.COOKIE_NAME, sess.dumps(data, s.web_session_secret),
                    httponly=True, samesite="lax", max_age=8 * 3600,
                    secure=s.public_base_url.startswith("https"))


async def _form(request: Request) -> dict:
    raw = (await request.body()).decode()
    return {k: v[0] for k, v in parse_qs(raw).items()}


# ----- routes -----
@router.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    s = get_settings()
    if not _enabled(s):
        return HTMLResponse(tpl.landing("", enabled=False))
    data = _read_session(request, s)
    # CHỈ chuyển sang wizard khi đã đăng nhập THẬT (có token). Session "dở dang" (mới có state
    # từ /login, chưa qua callback) phải ở lại landing — nếu không sẽ lặp / ⇄ /wizard.
    if data and data.get("tok"):
        return RedirectResponse("/wizard", status_code=303)
    return HTMLResponse(tpl.landing("/login", enabled=True))


@router.get("/login")
async def login():
    s = get_settings()
    if not _enabled(s):
        return RedirectResponse("/", status_code=303)
    state = secrets.token_urlsafe(16)
    oauth = GitHubOAuth.from_settings(s)
    try:
        url = oauth.authorize_url(_redirect_uri(s), state)
    finally:
        await oauth.aclose()
    resp = RedirectResponse(url, status_code=303)
    _attach_session(resp, {"state": state}, s)
    return resp


@router.get("/oauth/github/callback")
async def oauth_callback(request: Request, code: str = "", state: str = ""):
    s = get_settings()
    data = _read_session(request, s)
    if not data or not state or state != data.get("state") or not code:
        return RedirectResponse("/", status_code=303)
    oauth = GitHubOAuth.from_settings(s)
    try:
        token = await oauth.exchange_code(code, _redirect_uri(s))
        user = await oauth.get_user(token)
    except GitHubOAuthError as exc:
        log.warning("oauth callback lỗi: %s", exc)
        return RedirectResponse("/", status_code=303)
    finally:
        await oauth.aclose()
    resp = RedirectResponse("/wizard", status_code=303)
    _attach_session(resp, {"login": user["login"], "uid": user["id"],
                           "name": user["name"], "tok": token}, s)
    return resp


_DEV_REPOS = [
    {"full_name": "demo-org/shop", "installation_id": 1, "default_branch": "main"},
    {"full_name": "demo-org/api-gateway", "installation_id": 1, "default_branch": "main"},
]


@router.get("/dev/login")
async def dev_login():
    """CHỈ DEV (web_dev_login=true): đăng nhập giả, bỏ qua GitHub — để xem/thử wizard cục bộ."""
    s = get_settings()
    if not s.web_dev_login:
        return RedirectResponse("/", status_code=303)
    resp = RedirectResponse("/wizard", status_code=303)
    _attach_session(resp, {"login": "dev", "uid": 0, "name": "Dev User",
                           "tok": "dev", "state": "devstate"}, s)
    return resp


@router.get("/setup")
async def setup_callback():
    # GitHub redirect về đây sau khi cài App — repo mới sẽ hiện ở /wizard.
    return RedirectResponse("/wizard", status_code=303)


@router.get("/wizard", response_class=HTMLResponse)
async def wizard(request: Request):
    s = get_settings()
    data = _read_session(request, s)
    if not data or not data.get("tok"):
        return RedirectResponse("/", status_code=303)
    if s.web_dev_login and data.get("tok") == "dev":   # DEV: repo giả, không gọi GitHub
        repos, install_url = _DEV_REPOS, "#"
    else:
        oauth = GitHubOAuth.from_settings(s)
        try:
            repos = await oauth.accessible_repos(data["tok"])
            install_url = oauth.install_url(data.get("state", ""))
        except GitHubOAuthError as exc:
            log.warning("liệt kê repo lỗi: %s", exc)
            repos, install_url = [], oauth.install_url("")
        finally:
            await oauth.aclose()
    csrf = data.get("state", "")
    return HTMLResponse(tpl.wizard(data.get("name") or data["login"], repos, install_url,
                                   csrf, s.dedicated_container_enabled))


@router.post("/wizard/create", response_class=HTMLResponse)
async def wizard_create(request: Request, db: Session = Depends(get_db)):
    s = get_settings()
    data = _read_session(request, s)
    if not data or not data.get("tok"):
        return RedirectResponse("/", status_code=303)
    form = await _form(request)
    if form.get("csrf") != data.get("state"):
        return RedirectResponse("/wizard", status_code=303)

    repo_val = form.get("repo", "")
    if "|" not in repo_val:
        return HTMLResponse(_wizard_err(s, data, "Chưa chọn repo hợp lệ."))
    repo_full_name, inst = repo_val.rsplit("|", 1)
    bot_choice = form.get("bot_choice", "shared")
    try:
        result = await provision(
            db, s,
            owner_github_id=int(data["uid"]), owner_github_login=data["login"],
            owner_name=data.get("name") or data["login"],
            repo_full_name=repo_full_name, installation_id=int(inst),
            bot_choice=bot_choice,
            hosting_choice=form.get("hosting", "shared_instance"),
            display_name=(form.get("display_name") or "").strip() or None,
            bot_token=(form.get("bot_token") or "").strip() or None,
            base_branch=(form.get("base_branch") or "dev").strip(),
            prod_branch=(form.get("prod_branch") or "main").strip(),
        )
    except ProvisioningError as exc:
        db.rollback()
        return HTMLResponse(_wizard_err(s, data, str(exc)))
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        log.exception("provision lỗi")
        return HTMLResponse(_wizard_err(s, data, f"Lỗi tạo bot: {exc}"))
    return HTMLResponse(tpl.done(result, repo_full_name))


def _wizard_err(s, data: dict, msg: str) -> str:
    oauth = GitHubOAuth.from_settings(s)
    install_url = oauth.install_url(data.get("state", ""))
    return tpl.wizard(data.get("name") or data["login"], [], install_url,
                      data.get("state", ""), s.dedicated_container_enabled, error=msg)


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    s = get_settings()
    data = _read_session(request, s)
    if not data:
        return RedirectResponse("/", status_code=303)
    tenants = db.scalars(
        select(Tenant).where(Tenant.owner_github_id == int(data["uid"]))
    ).all()
    rows: list[dict] = []
    for t in tenants:
        repo = db.scalar(select(Repository).where(Repository.tenant_id == t.id))
        for b in db.scalars(select(Bot).where(Bot.tenant_id == t.id)).all():
            rows.append({"name": b.display_name or t.name,
                         "repo": repo.repo_full_name if repo else "-",
                         "username": b.username, "mode": b.mode,
                         "deployment": b.deployment_mode, "status": b.status})
    return HTMLResponse(tpl.dashboard(data.get("name") or data["login"], rows))


@router.get("/logout")
async def logout():
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie(sess.COOKIE_NAME)
    return resp
