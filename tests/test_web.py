"""Web wizard: cookie phiên ký HMAC (round-trip + chống giả mạo) + landing + render an toàn."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.web import session as sess
from app.web import templates as tpl


def test_session_roundtrip_and_tamper():
    secret = "s3cr3t"
    cookie = sess.dumps({"login": "alice", "uid": 42}, secret)
    data = sess.loads(cookie, secret)
    assert data["login"] == "alice" and data["uid"] == 42
    assert sess.loads(cookie, "wrong-secret") is None        # sai khoá → None
    assert sess.loads(cookie + "x", secret) is None          # đổi 1 ký tự → chữ ký hỏng
    assert sess.loads(None, secret) is None


def test_landing_disabled_when_unconfigured(monkeypatch):
    # Thiếu GitHub OAuth/PUBLIC_BASE_URL ⇒ wizard tắt, báo rõ. Monkeypatch để không phụ thuộc .env.
    from app.config import Settings
    from app.web import routes
    monkeypatch.setattr(routes, "get_settings", lambda: Settings(_env_file=None))
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "chưa được cấu hình" in resp.text


def test_wizard_html_escapes_user_input():
    html = tpl.wizard("<script>x</script>", [], "https://i", "csrf", dedicated_enabled=False)
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html


def _web_settings():
    from app.config import Settings
    return Settings(_env_file=None, public_base_url="https://x", github_oauth_client_id="c",
                    github_oauth_client_secret="d", github_app_slug="luna",
                    web_session_secret="sek")


def test_landing_no_redirect_loop_for_tokenless_session(monkeypatch, db):
    """Session 'dở dang' (state, chưa login) ở lại landing; login mà CHƯA có tenant → wizard."""
    from app.db import get_db
    from app.web import routes
    monkeypatch.setattr(routes, "get_settings", lambda: _web_settings())
    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app)
        client.cookies.set(sess.COOKIE_NAME, sess.dumps({"state": "x"}, "sek"))   # chưa có tok
        r = client.get("/", follow_redirects=False)
        assert r.status_code == 200 and "Tiếp tục với GitHub" in r.text
        # đã login (có tok) nhưng chưa tạo tenant nào → wizard
        client.cookies.set(sess.COOKIE_NAME,
                           sess.dumps({"tok": "t", "login": "a", "uid": 1, "name": "A"}, "sek"))
        r2 = client.get("/", follow_redirects=False)
        assert r2.status_code == 303 and r2.headers["location"] == "/wizard"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_landing_redirects_existing_tenant_to_dashboard(monkeypatch, db):
    """Đã login VÀ đã có tenant → vào thẳng /dashboard, không quay lại wizard."""
    from app.db import get_db
    from app.models import Tenant
    from app.web import routes
    monkeypatch.setattr(routes, "get_settings", lambda: _web_settings())
    db.add(Tenant(name="Acme", owner_github_id=7, owner_github_login="owner"))
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app)
        client.cookies.set(sess.COOKIE_NAME,
                           sess.dumps({"tok": "t", "login": "owner", "uid": 7, "name": "O"}, "sek"))
        r = client.get("/", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/dashboard"
    finally:
        app.dependency_overrides.pop(get_db, None)


def _dev_settings():
    """Settings với web_dev_login=True ⇒ /repo/add liệt kê repo giả, không gọi GitHub."""
    from app.config import Settings
    return Settings(_env_file=None, public_base_url="https://x", github_oauth_client_id="c",
                    github_oauth_client_secret="d", github_app_slug="luna",
                    web_session_secret="sek", web_dev_login=True)


def _dev_cookie(uid: int = 7, login: str = "owner"):
    return sess.dumps({"tok": "dev", "login": login, "uid": uid, "name": "O"}, "sek")


def test_repo_add_attaches_to_existing_tenant(monkeypatch, db):
    """POST /repo/add gắn repo vào tenant có sẵn — KHÔNG đẻ bot/user/link mới."""
    from app.db import get_db
    from app.models import Bot, Repository, Tenant, User
    from app.web import routes
    monkeypatch.setattr(routes, "get_settings", lambda: _dev_settings())
    t = Tenant(name="Acme", owner_github_id=7, owner_github_login="owner")
    db.add(t)
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app)
        client.cookies.set(sess.COOKIE_NAME, _dev_cookie())
        r = client.post("/repo/add", follow_redirects=False, data={
            "csrf": "", "tenant_id": str(t.id),
            "repo": "demo-org/shop|1", "base_branch": "dev", "prod_branch": "main"})
        assert r.status_code == 303 and r.headers["location"] == "/repositories"
        repos = db.query(Repository).filter_by(tenant_id=t.id).all()
        assert [x.repo_full_name for x in repos] == ["demo-org/shop"]
        assert repos[0].gh_installation_id == 1
        assert db.query(Bot).count() == 0 and db.query(User).count() == 0  # không provision
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_repo_add_rejects_other_users_tenant(monkeypatch, db):
    """Không cho thêm repo vào tenant của người khác (guard ownership)."""
    from app.db import get_db
    from app.models import Repository, Tenant
    from app.web import routes
    monkeypatch.setattr(routes, "get_settings", lambda: _dev_settings())
    victim = Tenant(name="Victim", owner_github_id=999, owner_github_login="other")
    db.add(victim)
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app)
        client.cookies.set(sess.COOKIE_NAME, _dev_cookie())   # uid=7, KHÔNG sở hữu victim
        r = client.post("/repo/add", follow_redirects=False, data={
            "csrf": "", "tenant_id": str(victim.id), "repo": "demo-org/shop|1"})
        assert r.status_code == 200                            # render lại kèm lỗi, không redirect
        assert db.query(Repository).count() == 0
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_repo_add_blocks_duplicate(monkeypatch, db):
    """Repo đã có trong tenant → báo lỗi, không tạo bản ghi trùng."""
    from app.db import get_db
    from app.models import Repository, Tenant
    from app.web import routes
    monkeypatch.setattr(routes, "get_settings", lambda: _dev_settings())
    t = Tenant(name="Acme", owner_github_id=7, owner_github_login="owner")
    db.add(t)
    db.flush()
    db.add(Repository(tenant_id=t.id, repo_full_name="demo-org/shop", gh_installation_id=1))
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app)
        client.cookies.set(sess.COOKIE_NAME, _dev_cookie())
        r = client.post("/repo/add", follow_redirects=False, data={
            "csrf": "", "tenant_id": str(t.id), "repo": "demo-org/shop|1"})
        assert r.status_code == 200
        assert db.query(Repository).filter_by(tenant_id=t.id).count() == 1   # vẫn 1
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_repo_add_rejects_forged_installation(monkeypatch, db):
    """Cross-tenant guard: repo/installation_id KHÔNG nằm trong danh sách user có quyền
    (kể cả repo name thật nhưng installation_id sai) → từ chối, không tạo bản ghi."""
    from app.db import get_db
    from app.models import Repository, Tenant
    from app.web import routes
    monkeypatch.setattr(routes, "get_settings", lambda: _dev_settings())
    t = Tenant(name="Acme", owner_github_id=7, owner_github_login="owner")
    db.add(t)
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app)
        client.cookies.set(sess.COOKIE_NAME, _dev_cookie())
        # repo name thật (demo-org/shop) nhưng installation_id của tenant khác (42 ∉ _DEV_REPOS)
        r = client.post("/repo/add", follow_redirects=False, data={
            "csrf": "", "tenant_id": str(t.id), "repo": "demo-org/shop|42"})
        assert r.status_code == 200                            # render lại kèm lỗi
        assert db.query(Repository).count() == 0
        # repo hoàn toàn không thuộc quyền user
        r2 = client.post("/repo/add", follow_redirects=False, data={
            "csrf": "", "tenant_id": str(t.id), "repo": "victim-org/private|99"})
        assert r2.status_code == 200
        assert db.query(Repository).count() == 0
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_wizard_create_rejects_forged_installation(monkeypatch, db):
    """Cross-tenant guard ở wizard: cặp repo|installation_id giả mạo → không provision."""
    from app.db import get_db
    from app.models import Repository, Tenant
    from app.web import routes
    monkeypatch.setattr(routes, "get_settings", lambda: _dev_settings())
    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app)
        cookie = sess.dumps({"tok": "dev", "login": "owner", "uid": 7, "name": "O",
                             "state": "x"}, "sek")
        client.cookies.set(sess.COOKIE_NAME, cookie)
        r = client.post("/wizard/create", follow_redirects=False, data={
            "csrf": "x", "repo": "victim-org/private|99", "bot_choice": "shared",
            "platform": "telegram"})
        assert r.status_code == 200                            # render lại kèm lỗi, không provision
        assert db.query(Tenant).count() == 0 and db.query(Repository).count() == 0
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_wizard_shows_channels_only_when_enabled():
    """Kênh Zalo/Messenger/Google Chat chỉ hiện trong wizard khi cờ enabled bật."""
    plain = tpl.wizard("U", [], "i", "c", dedicated_enabled=False)
    assert "value='zalo'" not in plain and "value='messenger'" not in plain
    assert "value='google_chat'" not in plain
    full = tpl.wizard("U", [], "i", "c", dedicated_enabled=False,
                      gchat_enabled=True, zalo_enabled=True, messenger_enabled=True)
    assert "value='zalo'" in full and "value='messenger'" in full
    assert "value='google_chat'" in full and "value='telegram'" in full


def test_wizard_banner_only_when_user_has_workspace():
    """Wizard hiện banner 'đã có workspace → thêm repo' chỉ khi has_workspace=True."""
    plain = tpl.wizard("U", [], "https://i", "c", dedicated_enabled=False)
    assert "/repo/add" not in plain
    with_ws = tpl.wizard("U", [], "https://i", "c", dedicated_enabled=False, has_workspace=True)
    assert "/repo/add" in with_ws and "alert-info" in with_ws


def test_repo_add_redirects_when_no_tenant(monkeypatch, db):
    """User chưa có tenant vào /repo/add → đẩy về /wizard (phải tạo bot trước)."""
    from app.db import get_db
    from app.web import routes
    monkeypatch.setattr(routes, "get_settings", lambda: _dev_settings())
    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app)
        client.cookies.set(sess.COOKIE_NAME, _dev_cookie())
        r = client.get("/repo/add", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/wizard"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_logout_clears_cookie():
    client = TestClient(app)
    resp = client.get("/logout", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
