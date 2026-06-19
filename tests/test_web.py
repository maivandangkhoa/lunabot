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


def test_landing_no_redirect_loop_for_tokenless_session(monkeypatch):
    """Session 'dở dang' (mới có state, chưa login) KHÔNG được redirect → tránh / ⇄ /wizard loop."""
    from app.config import Settings
    from app.web import routes
    s = Settings(_env_file=None, public_base_url="https://x", github_oauth_client_id="c",
                 github_oauth_client_secret="d", github_app_slug="luna", web_session_secret="sek")
    monkeypatch.setattr(routes, "get_settings", lambda: s)
    client = TestClient(app)
    client.cookies.set(sess.COOKIE_NAME, sess.dumps({"state": "x"}, "sek"))   # chưa có tok
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 200 and "Tiếp tục với GitHub" in r.text
    # đã login (có tok) → mới chuyển sang wizard
    client.cookies.set(sess.COOKIE_NAME,
                       sess.dumps({"tok": "t", "login": "a", "uid": 1, "name": "A"}, "sek"))
    r2 = client.get("/", follow_redirects=False)
    assert r2.status_code == 303 and r2.headers["location"] == "/wizard"


def test_logout_clears_cookie():
    client = TestClient(app)
    resp = client.get("/logout", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
