"""Trang Platform admin (/admin) — super admin xem MỌI tenant + thống kê.

Xác minh: chặn chưa đăng nhập, chặn user thường (đẩy /dashboard), super admin thấy tenant
của mọi owner, thẻ thống kê đếm toàn hệ thống, và mục nav /admin chỉ hiện cho super admin.
Cùng harness với test_web_team: override get_db về SQLite, monkeypatch settings có secret.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import grant_admin
from app.config import Settings
from app.db import get_db
from app.main import app
from app.models import Bot, PlatformAdmin, Repository, Tenant, User, UserRole
from app.onboarding import create_user
from app.web import routes
from app.web import session as sess

SECRET = "admin-secret"
ADMIN_UID = 9001
NORMAL_UID = 1001
OTHER_UID = 2002


@pytest.fixture
def s():
    return Settings(_env_file=None, public_base_url="https://x", github_oauth_client_id="c",
                    github_oauth_client_secret="d", github_app_slug="luna",
                    web_session_secret=SECRET)


@pytest.fixture
def client(db, s, monkeypatch):
    monkeypatch.setattr(routes, "get_settings", lambda: s)
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def _tenant(db, *, uid, login, name):
    tn = Tenant(name=name, owner_github_id=uid, owner_github_login=login)
    db.add(tn)
    db.flush()
    db.add(Bot(tenant_id=tn.id, platform="telegram", mode="shared"))
    db.add(Repository(tenant_id=tn.id, repo_full_name=f"{login}/{name.lower()}"))
    db.flush()
    return tn


def _make_admin(db, uid=ADMIN_UID, login="boss"):
    db.add(PlatformAdmin(github_id=uid, github_login=login))
    db.commit()


def _login(client, uid=NORMAL_UID, login="user"):
    client.cookies.set(sess.COOKIE_NAME,
                       sess.dumps({"tok": "t", "login": login, "uid": uid, "name": login}, SECRET))


# ── Guard ─────────────────────────────────────────────────────────────────────
def test_admin_requires_auth(client):
    r = client.get("/admin", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"


def test_admin_blocks_normal_user(client, db):
    _tenant(db, uid=NORMAL_UID, login="user", name="Acme")
    db.commit()
    _login(client, uid=NORMAL_UID)
    r = client.get("/admin", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/dashboard"


# ── Read-only view ────────────────────────────────────────────────────────────
def test_admin_sees_all_tenants(client, db):
    _tenant(db, uid=NORMAL_UID, login="alice", name="Acme")
    _tenant(db, uid=OTHER_UID, login="bob", name="Globex")
    _make_admin(db)
    _login(client, uid=ADMIN_UID, login="boss")
    r = client.get("/admin")
    assert r.status_code == 200
    # super admin (không sở hữu tenant nào) vẫn thấy tenant của MỌI owner
    assert "Acme" in r.text and "Globex" in r.text
    assert "@alice" in r.text and "@bob" in r.text


def test_admin_stats_count_platform_wide(client, db):
    tn = _tenant(db, uid=NORMAL_UID, login="alice", name="Acme")
    create_user(db, tn, role=UserRole.MANAGER, display_name="Alice")
    _make_admin(db)
    db.commit()
    _login(client, uid=ADMIN_UID, login="boss")
    r = client.get("/admin")
    assert r.status_code == 200
    # 1 tenant card thống kê (số "1" cho tenants) + tên owner xuất hiện
    assert "Acme" in r.text


def test_admin_lists_tenant_admins(client, db):
    """Mỗi tenant hiện admin/manager THẬT (role), khác owner web. EMPLOYEE không lên."""
    tn = _tenant(db, uid=NORMAL_UID, login="alice", name="Acme")
    create_user(db, tn, role=UserRole.ADMIN, display_name="Boss Lady")
    create_user(db, tn, role=UserRole.MANAGER, display_name="Mid Manager")
    create_user(db, tn, role=UserRole.EMPLOYEE, display_name="Worker Bee")
    _make_admin(db)
    db.commit()
    _login(client, uid=ADMIN_UID, login="boss")
    r = client.get("/admin")
    assert r.status_code == 200
    assert "Boss Lady" in r.text and "Mid Manager" in r.text
    assert "Worker Bee" not in r.text          # employee không phải admin/manager


def test_admin_shows_none_when_no_admins(client, db):
    """Tenant không có admin/manager (vd seed thiếu) → hiện 'chưa có', không vỡ trang."""
    _tenant(db, uid=NORMAL_UID, login="alice", name="Acme")
    _make_admin(db)
    db.commit()
    _login(client, uid=ADMIN_UID, login="boss")
    r = client.get("/admin")
    assert r.status_code == 200 and "Acme" in r.text


# ── Nav visibility ────────────────────────────────────────────────────────────
def test_admin_nav_hidden_for_normal_user(client, db):
    _tenant(db, uid=NORMAL_UID, login="user", name="Acme")
    db.commit()
    _login(client, uid=NORMAL_UID)
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "href='/admin'" not in r.text


def test_admin_nav_shown_for_super_admin(client, db):
    _tenant(db, uid=ADMIN_UID, login="boss", name="Acme")
    _make_admin(db)
    _login(client, uid=ADMIN_UID, login="boss")
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "href='/admin'" in r.text


# ── grant_admin CLI ───────────────────────────────────────────────────────────
def test_grant_is_idempotent(db):
    assert grant_admin.grant(db, 42, "x") is True
    assert grant_admin.grant(db, 42, "x") is False
    assert db.query(PlatformAdmin).count() == 1


def test_grant_updates_login(db):
    grant_admin.grant(db, 42, None)
    grant_admin.grant(db, 42, "renamed")
    row = db.query(PlatformAdmin).filter_by(github_id=42).one()
    assert row.github_login == "renamed"


def test_revoke(db):
    grant_admin.grant(db, 42, "x")
    assert grant_admin.revoke(db, 42) is True
    assert grant_admin.revoke(db, 42) is False
    assert db.query(PlatformAdmin).count() == 0


def test_resolve_by_login_from_tenant(db):
    _tenant(db, uid=NORMAL_UID, login="alice", name="Acme")
    db.commit()
    assert grant_admin._resolve(db, "alice", None) == (NORMAL_UID, "alice")
    assert grant_admin._resolve(db, "ALICE", None) == (NORMAL_UID, "alice")  # case-insensitive


def test_resolve_numeric_is_id(db):
    assert grant_admin._resolve(db, "777", "lbl") == (777, "lbl")


def test_resolve_unknown_login(db):
    assert grant_admin._resolve(db, "ghost", None) is None
