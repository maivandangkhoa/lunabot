"""Web wizard routes — đăng nhập GitHub OAuth → chọn repo → tạo bot (provision) → hướng dẫn.

Cố tình KHÔNG thêm dep: form parse thủ công (urllib) thay python-multipart; cookie ký HMAC
(app/web/session.py) thay itsdangerous; HTML render chuỗi (app/web/templates.py) thay Jinja2.
"""
from __future__ import annotations

import hmac
import logging
import secrets
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.github_oauth import GitHubOAuth, GitHubOAuthError
from app.models import (
    Bot, PlatformAdmin, Repository, Request as MaintRequest, Tenant,
)
from app.onboarding import InvalidBranchError, add_repository
from app.provisioning import ProvisioningError, provision
from app.web import i18n
from app.web import pages
from app.web.i18n import t
from app.web import session as sess
from app.web import styles as st
from app.web import templates as tpl

log = logging.getLogger("luna.web")
router = APIRouter(tags=["web"])


# ----- helpers -----
def _enabled(s) -> bool:
    return bool(s.public_base_url and s.github_oauth_client_id
                and s.github_oauth_client_secret and s.github_app_slug)


def _redirect_uri(s) -> str:
    return f"{s.public_base_url.rstrip('/')}/oauth/github/callback"


def _secure_cookie(s) -> bool:
    """Cookie phải Secure ở production (đứng sau HTTPS) — không phụ thuộc chuỗi URL cấu hình."""
    return s.is_production or bool(s.public_base_url and s.public_base_url.startswith("https"))


def _read_session(request: Request, s) -> dict | None:
    return sess.loads(request.cookies.get(sess.COOKIE_NAME), s.web_session_secret,
                      enc_key=s.bot_token_enc_key)


def _attach_session(resp, data: dict, s) -> None:
    resp.set_cookie(sess.COOKIE_NAME,
                    sess.dumps(data, s.web_session_secret, enc_key=s.bot_token_enc_key),
                    httponly=True, samesite="lax", max_age=8 * 3600,
                    secure=_secure_cookie(s))


async def _form(request: Request) -> dict:
    raw = (await request.body()).decode()
    return {k: v[0] for k, v in parse_qs(raw).items()}


def _csrf(data: dict, s=None) -> str:
    """Token CSRF NGẪU NHIÊN theo phiên, lưu trong cookie đã ký HMAC (client không giả được,
    xoay theo mỗi lần đăng nhập, không suy ra được từ uid). Dùng chung team/activity/approvals.
    Phiên cũ chưa có 'csrf' → chuỗi rỗng (SameSite=lax vẫn đỡ tới khi đăng nhập lại)."""
    return data.get("csrf") or ""


def _new_csrf() -> str:
    return secrets.token_urlsafe(24)


def _lang(request: Request) -> None:
    """Set ngôn ngữ cho request hiện tại: cookie đã chọn > Accept-Language > vi."""
    i18n.set_lang(i18n.pick(request.cookies.get(i18n.COOKIE),
                            request.headers.get("accept-language")))


# ----- routes -----
@router.get("/lang/{code}")
async def set_language(code: str, next: str = "/"):
    """Lưu ngôn ngữ người dùng chọn vào cookie rồi quay lại trang trước (chỉ path nội bộ)."""
    lang = i18n.normalize(code)
    # Chỉ redirect nội bộ: chặn cả URL protocol-relative (//evil.com) và backslash-trick.
    safe = next.startswith("/") and not next.startswith(("//", "/\\"))
    target = next if safe else "/"
    resp = RedirectResponse(target, status_code=303)
    resp.set_cookie(i18n.COOKIE, lang, max_age=365 * 24 * 3600, samesite="lax",
                    secure=_secure_cookie(get_settings()))
    return resp


@router.get("/", response_class=HTMLResponse)
async def landing(request: Request, db: Session = Depends(get_db)):
    s = get_settings()
    _lang(request)
    if not _enabled(s):
        return HTMLResponse(tpl.landing("", enabled=False))
    data = _read_session(request, s)
    # CHỈ chuyển hướng khi đã đăng nhập THẬT (có token). Session "dở dang" (mới có state
    # từ /login, chưa qua callback) phải ở lại landing — nếu không sẽ lặp / ⇄ /wizard.
    if data and data.get("tok"):
        return RedirectResponse(_home(db, data), status_code=303)
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
async def oauth_callback(request: Request, code: str = "", state: str = "",
                         db: Session = Depends(get_db)):
    s = get_settings()
    data = _read_session(request, s)
    if (not data or not state or not code
            or not hmac.compare_digest(state, data.get("state") or "")):
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
    new_data = {"login": user["login"], "uid": user["id"],
                "name": user["name"], "tok": token, "csrf": _new_csrf()}
    resp = RedirectResponse(_home(db, new_data), status_code=303)
    _attach_session(resp, new_data, s)
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
                           "tok": "dev", "state": secrets.token_urlsafe(16),
                           "csrf": _new_csrf()}, s)
    return resp


@router.get("/setup")
async def setup_callback():
    # GitHub redirect về đây sau khi cài App — repo mới sẽ hiện ở /wizard.
    return RedirectResponse("/wizard", status_code=303)


async def _list_repos(s, data: dict) -> tuple[list[dict], str]:
    """Liệt kê repo user có thể truy cập + link cài/đổi quyền GitHub App. Dùng chung cho
    wizard (tạo bot) và trang thêm repo. DEV (web_dev_login): repo giả, không gọi GitHub."""
    if s.web_dev_login and data.get("tok") == "dev":
        return _DEV_REPOS, "#"
    oauth = GitHubOAuth.from_settings(s)
    try:
        repos = await oauth.accessible_repos(data["tok"])
        install_url = oauth.install_url(data.get("state", ""))
    except GitHubOAuthError as exc:
        log.warning("liệt kê repo lỗi: %s", exc)
        repos, install_url = [], oauth.install_url("")
    finally:
        await oauth.aclose()
    return repos, install_url


async def _verify_repo_grant(s, data: dict, repo_full_name: str, installation_id: int) -> bool:
    """Bảo mật multi-tenant: xác nhận user THỰC SỰ có quyền trên (repo, installation) bằng
    token OAuth của họ — KHÔNG tin cặp `repo|installation_id` echo từ form (client sửa được).
    Nếu bỏ kiểm: attacker gắn private repo + installation_id của tenant KHÁC vào tenant mình
    rồi clone (App JWT mint token cho mọi installation) ⇒ đọc source tenant khác."""
    repos, _ = await _list_repos(s, data)
    return any(r.get("full_name") == repo_full_name
               and int(r.get("installation_id")) == installation_id
               for r in repos)


@router.get("/wizard", response_class=HTMLResponse)
async def wizard(request: Request, db: Session = Depends(get_db)):
    s = get_settings()
    _lang(request)
    data = _read_session(request, s)
    if not data or not data.get("tok"):
        return RedirectResponse("/", status_code=303)
    repos, install_url = await _list_repos(s, data)
    return HTMLResponse(tpl.wizard(data.get("name") or data["login"], repos, install_url,
                                   _csrf(data), s.dedicated_container_enabled,
                                   gchat_enabled=s.google_chat_enabled,
                                   zalo_enabled=s.zalo_enabled,
                                   messenger_enabled=s.messenger_enabled,
                                   slack_enabled=s.slack_enabled,
                                   has_workspace=bool(_tenants(db, data))))


@router.post("/wizard/create", response_class=HTMLResponse)
async def wizard_create(request: Request, db: Session = Depends(get_db)):
    s = get_settings()
    _lang(request)
    data = _read_session(request, s)
    if not data or not data.get("tok"):
        return RedirectResponse("/", status_code=303)
    form = await _form(request)
    if not hmac.compare_digest(form.get("csrf", ""), _csrf(data)):
        return RedirectResponse("/wizard", status_code=303)

    repo_val = form.get("repo", "")
    if "|" not in repo_val or not repo_val.rsplit("|", 1)[1].isdigit():
        return HTMLResponse(_wizard_err(s, data, "Chưa chọn repo hợp lệ."))
    repo_full_name, inst = repo_val.rsplit("|", 1)
    if not await _verify_repo_grant(s, data, repo_full_name, int(inst)):
        return HTMLResponse(_wizard_err(s, data, "Repo không thuộc quyền truy cập của bạn."))
    bot_choice = form.get("bot_choice", "shared")
    platform = form.get("platform", "telegram")
    try:
        result = await provision(
            db, s,
            owner_github_id=int(data["uid"]), owner_github_login=data["login"],
            owner_name=data.get("name") or data["login"],
            repo_full_name=repo_full_name, installation_id=int(inst),
            bot_choice=bot_choice, platform=platform,
            hosting_choice=form.get("hosting", "shared_instance"),
            display_name=(form.get("display_name") or "").strip() or None,
            bot_token=(form.get("bot_token") or "").strip() or None,
            base_branch=(form.get("base_branch") or "dev").strip(),
            prod_branch=(form.get("prod_branch") or "main").strip(),
            dev_mode=form.get("dev_mode") == "1",
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
                      _csrf(data), s.dedicated_container_enabled,
                      gchat_enabled=s.google_chat_enabled,
                      zalo_enabled=s.zalo_enabled, messenger_enabled=s.messenger_enabled,
                      slack_enabled=s.slack_enabled, error=msg)


# ----- app-shell pages (sidebar) -----
def is_super_admin(db: Session, data: dict | None) -> bool:
    """Super admin nền tảng = có dòng platform_admins khớp github_id (uid trong session)."""
    if not data or data.get("uid") is None:
        return False
    return db.scalar(
        select(PlatformAdmin.id).where(PlatformAdmin.github_id == int(data["uid"]))
    ) is not None


def _auth(request: Request, db: Session | None = None) -> dict | None:
    """Set ngôn ngữ + đọc session. None ⇒ caller redirect về '/'. Khi truyền db, set cờ
    hiển thị mục Platform admin trên sidebar (chỉ super admin mới thấy)."""
    _lang(request)
    data = _read_session(request, get_settings())
    if db is not None:
        st.set_admin_nav(is_super_admin(db, data))
    return data


def _tenants(db: Session, data: dict) -> list[Tenant]:
    return list(db.scalars(
        select(Tenant).where(Tenant.owner_github_id == int(data["uid"]))
    ).all())


def _home(db: Session, data: dict) -> str:
    """Đích mặc định sau đăng nhập: đã có tenant → dashboard; chưa có → wizard tạo bot."""
    return "/dashboard" if _tenants(db, data) else "/wizard"


def _fmt(dt) -> str:
    return dt.strftime("%Y-%m-%d %H:%M") if dt else ""


def _bot_rows(db: Session, tenants: list[Tenant]) -> list[dict]:
    rows: list[dict] = []
    for t in tenants:
        repo = db.scalar(select(Repository).where(Repository.tenant_id == t.id))
        for b in db.scalars(select(Bot).where(Bot.tenant_id == t.id)).all():
            rows.append({"name": b.display_name or t.name,
                         "repo": repo.repo_full_name if repo else "-",
                         "username": b.username, "mode": b.mode,
                         "deployment": b.deployment_mode, "status": b.status})
    return rows


def _repo_name_map(db: Session, tenant_ids: list[int]) -> dict[int, str]:
    repos = db.scalars(
        select(Repository).where(Repository.tenant_id.in_(tenant_ids))
    ).all() if tenant_ids else []
    return {r.id: r.repo_full_name for r in repos}


def _request_rows(db: Session, tenant_ids: list[int], limit: int | None = None) -> list[dict]:
    if not tenant_ids:
        return []
    names = _repo_name_map(db, tenant_ids)
    q = (select(MaintRequest)
         .where(MaintRequest.tenant_id.in_(tenant_ids))
         .order_by(MaintRequest.updated_at.desc()))
    if limit:
        q = q.limit(limit)
    return [{"id": r.id, "title": r.title, "status": r.status.value,
             "repo": names.get(r.repo_id, "—"), "updated": _fmt(r.updated_at),
             "pr_url": r.pr_url, "pr_number": r.pr_number}
            for r in db.scalars(q).all()]


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    data = _auth(request, db)
    if not data:
        return RedirectResponse("/", status_code=303)
    tenants = _tenants(db, data)
    ids = [t.id for t in tenants]
    bots = _bot_rows(db, tenants)
    recent = _request_rows(db, ids, limit=5)
    active = {"new", "analyzing", "clarifying", "plan_review", "executing", "verify",
              "merged_dev", "await_manager"}
    n_req = db.scalar(select(func.count()).select_from(MaintRequest)
                      .where(MaintRequest.tenant_id.in_(ids))) if ids else 0
    stats = {"bots": len(bots), "repos": len(_repo_name_map(db, ids)),
             "requests": n_req or 0,
             "active": sum(1 for r in recent if r["status"] in active)}
    return HTMLResponse(pages.overview(data.get("name") or data["login"], stats, recent))


@router.get("/bots", response_class=HTMLResponse)
async def bots(request: Request, db: Session = Depends(get_db)):
    data = _auth(request, db)
    if not data:
        return RedirectResponse("/", status_code=303)
    rows = _bot_rows(db, _tenants(db, data))
    return HTMLResponse(tpl.bots(data.get("name") or data["login"], rows))


@router.get("/repositories", response_class=HTMLResponse)
async def repositories(request: Request, db: Session = Depends(get_db)):
    data = _auth(request, db)
    if not data:
        return RedirectResponse("/", status_code=303)
    tenants = _tenants(db, data)
    rows: list[dict] = []
    for t in tenants:
        n_bots = db.scalar(select(func.count()).select_from(Bot)
                           .where(Bot.tenant_id == t.id)) or 0
        for repo in db.scalars(select(Repository).where(Repository.tenant_id == t.id)).all():
            rows.append({"full_name": repo.repo_full_name, "base": repo.base_branch,
                         "prod": repo.prod_branch,
                         "installed": repo.gh_installation_id is not None, "bots": n_bots})
    return HTMLResponse(pages.repositories(data.get("name") or data["login"], rows))


def _tenant_dicts(tenants: list[Tenant]) -> list[dict]:
    return [{"id": t.id, "name": t.name} for t in tenants]


@router.get("/repo/add", response_class=HTMLResponse)
async def repo_add(request: Request, tenant: str = "", db: Session = Depends(get_db)):
    """Thêm repo vào tenant ĐÃ CÓ — KHÔNG provision (không đẻ bot/user/link mới)."""
    data = _auth(request, db)
    if not data or not data.get("tok"):
        return RedirectResponse("/", status_code=303)
    tenants = _tenants(db, data)
    if not tenants:                       # chưa có tenant → phải qua wizard tạo bot trước
        return RedirectResponse("/wizard", status_code=303)
    s = get_settings()
    repos, install_url = await _list_repos(s, data)
    sel = tenant if any(str(t.id) == tenant for t in tenants) else ""
    return HTMLResponse(tpl.add_repo(
        data.get("name") or data["login"], _tenant_dicts(tenants), repos, install_url,
        _csrf(data), selected_tenant=sel))


@router.post("/repo/add", response_class=HTMLResponse)
async def repo_add_create(request: Request, db: Session = Depends(get_db)):
    s = get_settings()
    data = _auth(request, db)
    if not data or not data.get("tok"):
        return RedirectResponse("/", status_code=303)
    form = await _form(request)
    if not hmac.compare_digest(form.get("csrf", ""), _csrf(data)):
        return RedirectResponse("/repo/add", status_code=303)
    tenants = _tenants(db, data)
    tid = form.get("tenant_id", "")
    tenant = next((t for t in tenants if str(t.id) == tid), None)  # guard: chỉ tenant của user
    repo_val = form.get("repo", "")
    err: str | None = None
    if tenant is None:
        err = t("repoadd.err.tenant")
    elif "|" not in repo_val or not repo_val.rsplit("|", 1)[1].isdigit():
        err = t("repoadd.err.repo")
    else:
        repo_full_name, inst = repo_val.rsplit("|", 1)
        exists = db.scalar(select(Repository).where(
            Repository.tenant_id == tenant.id,
            Repository.repo_full_name == repo_full_name))
        if exists is not None:
            err = t("repoadd.err.exists", name=repo_full_name)
        elif not await _verify_repo_grant(s, data, repo_full_name, int(inst)):
            err = t("repoadd.err.repo")
        else:
            try:
                add_repository(db, tenant, repo_full_name, int(inst),
                               base_branch=(form.get("base_branch") or "dev").strip(),
                               prod_branch=(form.get("prod_branch") or "main").strip())
            except InvalidBranchError as exc:
                db.rollback()
                err = str(exc)
            else:
                db.commit()
                return RedirectResponse("/repositories", status_code=303)
    repos, install_url = await _list_repos(s, data)
    return HTMLResponse(tpl.add_repo(
        data.get("name") or data["login"], _tenant_dicts(tenants), repos, install_url,
        _csrf(data), selected_tenant=tid, error=err))


@router.get("/requests", response_class=HTMLResponse)
async def requests(request: Request, db: Session = Depends(get_db)):
    data = _auth(request, db)
    if not data:
        return RedirectResponse("/", status_code=303)
    ids = [t.id for t in _tenants(db, data)]
    rows = _request_rows(db, ids)
    csrf = _csrf(data, get_settings())
    return HTMLResponse(pages.requests(data.get("name") or data["login"], rows, csrf))


@router.get("/settings", response_class=HTMLResponse)
async def settings(request: Request, db: Session = Depends(get_db)):
    data = _auth(request, db)
    if not data:
        return RedirectResponse("/", status_code=303)
    tenants = _tenants(db, data)
    account = {"login": data.get("login"), "name": data.get("name")}
    ws = [{"name": t.name, "plan": t.plan} for t in tenants]
    return HTMLResponse(pages.settings(data.get("name") or data["login"], account, ws))


@router.get("/logout")
async def logout():
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie(sess.COOKIE_NAME)
    return resp
