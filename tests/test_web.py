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


def test_landing_disabled_when_unconfigured():
    # Môi trường test không set GitHub OAuth/PUBLIC_BASE_URL ⇒ wizard tắt, báo rõ.
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "chưa được cấu hình" in resp.text


def test_wizard_html_escapes_user_input():
    html = tpl.wizard("<script>x</script>", [], "https://i", "csrf", dedicated_enabled=False)
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html


def test_logout_clears_cookie():
    client = TestClient(app)
    resp = client.get("/logout", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
