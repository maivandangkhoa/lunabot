"""Tests trang usage web (/usage của chủ workspace + /admin/usage của super admin).

Cùng harness test_web_admin: override get_db về SQLite, monkeypatch settings có secret.
Khẳng định: guard đăng nhập, cô lập tenant (chỉ thấy workspace mình), admin thấy breakdown
mọi tenant + tỷ trọng, và các hàm format tiền/token.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import get_db
from app.main import app
from app.models import PlatformAdmin, Tenant, UsageRecord
from app.web import routes
from app.web import session as sess
from app.web.usage import fmt_cost, fmt_tokens

SECRET = "usage-secret"
ADMIN_UID = 9001
ALICE_UID = 1001
BOB_UID = 2002


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


def _login(client, uid, login="user"):
    client.cookies.set(sess.COOKIE_NAME,
                       sess.dumps({"tok": "t", "login": login, "uid": uid, "name": login}, SECRET))


def _tenant(db, *, uid, login, name):
    tn = Tenant(name=name, owner_github_id=uid, owner_github_login=login)
    db.add(tn)
    db.flush()
    return tn


def _rec(db, tenant_id, *, phase="execute", cost=1.0, tok_in=1000, tok_out=200,
         status="ok", request_id=None):
    db.add(UsageRecord(tenant_id=tenant_id, request_id=request_id, phase=phase,
                       status=status, auth_mode="subscription", input_tokens=tok_in,
                       output_tokens=tok_out, cost_usd=cost))


# ── format helpers ────────────────────────────────────────────────────────────
def test_fmt_cost():
    assert fmt_cost(0) == "$0.00"
    assert fmt_cost(0.4321) == "$0.43"
    assert fmt_cost(0.0042) == "$0.0042"
    assert fmt_cost(1234.5) == "$1,234.50"


def test_fmt_tokens():
    assert fmt_tokens(999) == "999"
    assert fmt_tokens(12_300) == "12.3k"
    assert fmt_tokens(2_500_000) == "2.5M"


# ── /usage (chủ workspace) ────────────────────────────────────────────────────
def test_usage_requires_auth(client):
    r = client.get("/usage", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"


def test_usage_isolated_per_owner(client, db):
    """Chủ workspace chỉ thấy số của tenant MÌNH — cost tenant khác không lộ."""
    a = _tenant(db, uid=ALICE_UID, login="alice", name="Acme")
    b = _tenant(db, uid=BOB_UID, login="bob", name="Globex")
    _rec(db, a.id, phase="analyze", cost=0.25)
    _rec(db, a.id, phase="execute", cost=1.75)
    _rec(db, b.id, phase="execute", cost=88.0)
    db.commit()
    _login(client, ALICE_UID, "alice")
    r = client.get("/usage")
    assert r.status_code == 200
    assert "$2.00" in r.text            # 0.25 + 1.75 của Acme
    assert "$88" not in r.text          # tenant khác không lộ
    assert "analyze" in r.text and "execute" in r.text  # breakdown theo phase


def test_usage_empty_state(client, db):
    _tenant(db, uid=ALICE_UID, login="alice", name="Acme")
    db.commit()
    _login(client, ALICE_UID, "alice")
    r = client.get("/usage")
    assert r.status_code == 200
    assert "Chưa có dữ liệu sử dụng" in r.text


# ── /admin/usage (super admin) ────────────────────────────────────────────────
def test_admin_usage_blocks_normal_user(client, db):
    _tenant(db, uid=ALICE_UID, login="alice", name="Acme")
    db.commit()
    _login(client, ALICE_UID, "alice")
    r = client.get("/admin/usage", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/dashboard"


def test_admin_usage_shows_all_tenants_and_share(client, db):
    a = _tenant(db, uid=ALICE_UID, login="alice", name="Acme")
    b = _tenant(db, uid=BOB_UID, login="bob", name="Globex")
    _rec(db, a.id, cost=3.0)
    _rec(db, b.id, cost=1.0, status="limit")
    db.add(PlatformAdmin(github_id=ADMIN_UID, github_login="boss"))
    db.commit()
    _login(client, ADMIN_UID, "boss")
    r = client.get("/admin/usage")
    assert r.status_code == 200
    assert "Acme" in r.text and "Globex" in r.text
    assert "$4.00" in r.text            # tổng toàn hệ thống
    assert "75.0%" in r.text and "25.0%" in r.text  # tỷ trọng
    # chưa cấu hình trần → hiện hướng dẫn env, không hiện %
    assert "SUB_QUOTA_USD_5H" in r.text


def test_admin_usage_quota_bar_when_configured(client, db, s, monkeypatch):
    a = _tenant(db, uid=ALICE_UID, login="alice", name="Acme")
    _rec(db, a.id, cost=5.0)
    db.add(PlatformAdmin(github_id=ADMIN_UID, github_login="boss"))
    db.commit()
    from app.web import usage as usage_web
    monkeypatch.setattr(usage_web, "get_settings",
                        lambda: Settings(_env_file=None, sub_quota_usd_5h=10.0,
                                         sub_quota_usd_week=50.0))
    _login(client, ADMIN_UID, "boss")
    r = client.get("/admin/usage")
    assert r.status_code == 200
    assert "$5.00 / $10.00 (50%)" in r.text
    assert "$5.00 / $50.00 (10%)" in r.text
