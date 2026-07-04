"""Web approval (/requests/{id}/approve|reject) — chủ workspace duyệt/từ chối merge production.

Xác minh: approve → merge main + CLOSED + Approval(APPROVED); reject → CANCELLED + Approval(REJECTED);
auth/CSRF/ownership/wrong-status đều no-op. Side-effect GitHub/git/adapter dùng fake (monkeypatch
hook trong app.web.approvals). Override get_db về SQLite in-memory.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import get_db
from app.main import app
from app.models import (
    ApprovalDecision, Bot, Repository, Request, RequestStatus, Tenant, User, UserRole,
)
from app.web import approvals as appr
from app.web import routes
from app.web import session as sess
from tests.conftest import FakeGit, FakeGitHub, RecordingTelegram

SECRET = "appr-secret"
OWNER_UID = 4001
OTHER_UID = 5002


@pytest.fixture
def s():
    return Settings(_env_file=None, public_base_url="https://x", github_oauth_client_id="c",
                    github_oauth_client_secret="d", github_app_slug="luna",
                    web_session_secret=SECRET)


@pytest.fixture
def gh():
    return FakeGitHub()


@pytest.fixture
def client(db, s, gh, monkeypatch):
    monkeypatch.setattr(routes, "get_settings", lambda: s)
    monkeypatch.setattr(appr, "get_settings", lambda: s)
    monkeypatch.setattr(appr, "_github", lambda: gh)
    monkeypatch.setattr(appr, "_git", lambda: FakeGit())
    monkeypatch.setattr(appr, "_reply_adapter", lambda db, req, st: RecordingTelegram())
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def _seed(db, *, uid=OWNER_UID, status=RequestStatus.AWAIT_MANAGER, with_admin=True):
    tn = Tenant(name="Acme", owner_github_id=uid, owner_github_login="owner")
    db.add(tn)
    db.flush()
    db.add(Bot(tenant_id=tn.id, platform="telegram", mode="shared"))
    repo = Repository(tenant_id=tn.id, repo_full_name="acme/widgets", gh_installation_id=123,
                      base_branch="dev", prod_branch="main")
    db.add(repo)
    db.flush()
    if with_admin:
        db.add(User(tenant_id=tn.id, role=UserRole.ADMIN, display_name="Owner",
                    platform="telegram", platform_user_id="adm-1"))
    emp = User(tenant_id=tn.id, role=UserRole.EMPLOYEE, display_name="Bob",
               platform="telegram", platform_user_id="emp-1")
    db.add(emp)
    db.flush()
    req = Request(tenant_id=tn.id, repo_id=repo.id, requester_user_id=emp.id, title="Add X",
                  status=status, pr_number=7, pr_url="https://github.com/acme/widgets/pull/7",
                  branch_name="bot/req-1", dev_merge_sha="abc123",
                  origin_platform="telegram", origin_chat_id="emp-1")
    db.add(req)
    db.flush()
    db.commit()
    return tn, repo, req


_SESS_CSRF = "sess-csrf-token"


def _login(client, uid=OWNER_UID):
    client.cookies.set(sess.COOKIE_NAME, sess.dumps(
        {"tok": "t", "login": "owner", "uid": uid, "name": "Owner", "csrf": _SESS_CSRF},
        SECRET))


def _csrf(uid=OWNER_UID):
    return _SESS_CSRF


def test_approve_merges_to_main_and_closes(client, db, gh):
    _, _, req = _seed(db)
    _login(client)
    r = client.post(f"/requests/{req.id}/approve", follow_redirects=False,
                    data={"csrf": _csrf()})
    assert r.status_code == 303 and r.headers["location"] == "/requests"
    db.refresh(req)
    assert req.status == RequestStatus.CLOSED
    assert any(a.decision == ApprovalDecision.APPROVED for a in req.approvals)
    assert "bot/req-1" in gh.deleted_branches  # nhánh feature đã dọn
    # PR release base=main đã tạo + merge
    assert any(p["base"] == "main" for p in gh.created_prs) and gh.merged


def test_reject_cancels_and_reverts(client, db, gh):
    _, _, req = _seed(db)
    _login(client)
    r = client.post(f"/requests/{req.id}/reject", follow_redirects=False, data={"csrf": _csrf()})
    assert r.status_code == 303 and r.headers["location"] == "/requests"
    db.refresh(req)
    assert req.status == RequestStatus.CANCELLED
    assert any(a.decision == ApprovalDecision.REJECTED for a in req.approvals)
    assert 7 in gh.closed_prs  # PR dev đã đóng


def test_approve_requires_auth(client, db):
    _, _, req = _seed(db)
    r = client.post(f"/requests/{req.id}/approve", follow_redirects=False, data={"csrf": _csrf()})
    assert r.status_code == 303 and r.headers["location"] == "/"
    db.refresh(req)
    assert req.status == RequestStatus.AWAIT_MANAGER


def test_approve_rejected_without_csrf(client, db):
    _, _, req = _seed(db)
    _login(client)
    r = client.post(f"/requests/{req.id}/approve", follow_redirects=False, data={"csrf": "wrong"})
    assert r.status_code == 303 and r.headers["location"] == "/requests"
    db.refresh(req)
    assert req.status == RequestStatus.AWAIT_MANAGER  # không merge


def test_other_owner_cannot_approve(client, db):
    _, _, req = _seed(db, uid=OTHER_UID)  # request của owner khác
    _login(client, uid=OWNER_UID)
    client.post(f"/requests/{req.id}/approve", data={"csrf": _csrf(OWNER_UID)})
    db.refresh(req)
    assert req.status == RequestStatus.AWAIT_MANAGER  # bị chặn


def test_wrong_status_is_noop(client, db, gh):
    _, _, req = _seed(db, status=RequestStatus.VERIFY)
    _login(client)
    client.post(f"/requests/{req.id}/approve", data={"csrf": _csrf()})
    db.refresh(req)
    assert req.status == RequestStatus.VERIFY and not gh.merged


def test_requests_page_shows_buttons_only_for_await_manager(client, db):
    _seed(db)  # AWAIT_MANAGER
    _login(client)
    r = client.get("/requests")
    assert r.status_code == 200
    assert "/approve" in r.text and "/reject" in r.text


def test_requests_page_no_buttons_for_other_status(client, db):
    _seed(db, status=RequestStatus.VERIFY)
    _login(client)
    r = client.get("/requests")
    assert "/approve" not in r.text
