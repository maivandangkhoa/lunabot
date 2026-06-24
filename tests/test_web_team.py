"""Trang Team (/users): quản lý người dùng + workspace qua web — invite/role/unlink/rename.

Xác minh: render, CSRF, và cách ly theo owner (owner_github_id) — không động được tenant
của owner khác. Override get_db về SQLite in-memory + monkeypatch settings có session secret.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import get_db
from app.main import app
from app.models import Bot, Tenant, User, UserRole
from app.onboarding import create_user
from app.web import routes
from app.web import session as sess
from app.web import team as team_mod

SECRET = "team-secret"
OWNER_UID = 1001
OTHER_UID = 2002


@pytest.fixture
def s():
    return Settings(_env_file=None, public_base_url="https://x", github_oauth_client_id="c",
                    github_oauth_client_secret="d", github_app_slug="luna",
                    web_session_secret=SECRET)


@pytest.fixture
def client(db, s, monkeypatch):
    monkeypatch.setattr(routes, "get_settings", lambda: s)
    monkeypatch.setattr(team_mod, "get_settings", lambda: s)
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def _seed(db, *, uid=OWNER_UID, name="Acme"):
    tn = Tenant(name=name, owner_github_id=uid, owner_github_login="owner")
    db.add(tn)
    db.flush()
    db.add(Bot(tenant_id=tn.id, platform="telegram", mode="shared"))
    db.flush()
    return tn


def _login(client, uid=OWNER_UID):
    client.cookies.set(sess.COOKIE_NAME,
                       sess.dumps({"tok": "t", "login": "owner", "uid": uid, "name": "Owner"}, SECRET))


def _csrf(uid=OWNER_UID, s=None):
    return team_mod._csrf({"uid": uid}, s or Settings(_env_file=None, web_session_secret=SECRET))


def test_users_requires_auth(client):
    r = client.get("/users", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"


def test_users_lists_owned_members(client, db):
    tn = _seed(db)
    create_user(db, tn, role=UserRole.MANAGER, display_name="Alice")
    db.commit()
    _login(client)
    r = client.get("/users")
    assert r.status_code == 200
    assert "Alice" in r.text and tn.name in r.text


def test_invite_creates_pending_user(client, db, s):
    tn = _seed(db)
    db.commit()
    _login(client)
    r = client.post("/users/invite", follow_redirects=False,
                    data={"csrf": _csrf(s=s), "tenant_id": tn.id, "role": "manager", "name": "Bob"})
    assert r.status_code == 303 and r.headers["location"] == "/users"
    u = db.query(User).filter_by(display_name="Bob").one()
    assert u.role == UserRole.MANAGER and u.tenant_id == tn.id
    assert u.platform_user_id is None and u.link_token  # chờ liên kết, có token


def test_invite_rejected_without_csrf(client, db):
    tn = _seed(db)
    db.commit()
    _login(client)
    r = client.post("/users/invite", follow_redirects=False,
                    data={"csrf": "wrong", "tenant_id": tn.id, "role": "admin", "name": "Eve"})
    assert r.status_code == 303
    assert db.query(User).count() == 0  # không tạo gì


def test_role_change(client, db, s):
    tn = _seed(db)
    u = create_user(db, tn, role=UserRole.EMPLOYEE, display_name="Carol")
    db.commit()
    _login(client)
    client.post("/users/role", data={"csrf": _csrf(s=s), "user_id": u.id, "role": "admin"})
    db.refresh(u)
    assert u.role == UserRole.ADMIN


def test_unlink_regenerates_token(client, db, s):
    tn = _seed(db)
    u = create_user(db, tn, role=UserRole.EMPLOYEE, display_name="Dan")
    u.platform_user_id = "555"
    u.link_token = None
    db.commit()
    _login(client)
    client.post("/users/unlink", data={"csrf": _csrf(s=s), "user_id": u.id})
    db.refresh(u)
    assert u.platform_user_id is None and u.link_token  # gỡ + cấp token mới


def test_tenant_rename(client, db, s):
    tn = _seed(db)
    db.commit()
    _login(client)
    client.post("/tenants/rename", data={"csrf": _csrf(s=s), "tenant_id": tn.id, "name": "Renamed"})
    db.refresh(tn)
    assert tn.name == "Renamed"


def test_cannot_touch_other_owners_tenant(client, db, s):
    mine = _seed(db, uid=OWNER_UID, name="Mine")
    theirs = _seed(db, uid=OTHER_UID, name="Theirs")
    victim = create_user(db, theirs, role=UserRole.EMPLOYEE, display_name="Victim")
    db.commit()
    _login(client, uid=OWNER_UID)
    # đổi tên tenant người khác → bị chặn
    client.post("/tenants/rename", data={"csrf": _csrf(s=s), "tenant_id": theirs.id, "name": "Hacked"})
    db.refresh(theirs)
    assert theirs.name == "Theirs"
    # đổi role user người khác → bị chặn
    client.post("/users/role", data={"csrf": _csrf(s=s), "user_id": victim.id, "role": "admin"})
    db.refresh(victim)
    assert victim.role == UserRole.EMPLOYEE
    # /users chỉ liệt kê tenant của mình
    r = client.get("/users")
    assert "Mine" in r.text and "Theirs" not in r.text
