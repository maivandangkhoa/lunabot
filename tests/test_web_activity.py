"""Trang Activity (/activity) — bộ lọc (thời gian/loại sự kiện/trạng thái request) + xoá log.

Xác minh: GET lọc đúng theo kind/status/time; POST /activity/clear chỉ xoá sự kiện khớp bộ
lọc hiện tại (giữ phần còn lại), guard auth/CSRF, redirect kèm querystring lọc. DB SQLite
in-memory (conftest `db`); request_events là nhật ký hiển thị nên xoá không đụng FSM.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import get_db
from app.main import app
from app.models import (
    EventDirection, EventKind, Repository, Request, RequestEvent, RequestStatus, Tenant, User,
    UserRole,
)
from app.web import routes
from app.web import session as sess

SECRET = "act-secret"
OWNER_UID = 7001
OTHER_UID = 7002


@pytest.fixture
def s():
    return Settings(_env_file=None, web_session_secret=SECRET)


@pytest.fixture
def client(db, s, monkeypatch):
    monkeypatch.setattr(routes, "get_settings", lambda: s)
    from app.web import activity as act
    monkeypatch.setattr(act, "get_settings", lambda: s)
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def _now():
    return datetime.now(timezone.utc)


def _seed(db, *, uid=OWNER_UID, status=RequestStatus.EXECUTING):
    tn = Tenant(name="Acme", owner_github_id=uid, owner_github_login="owner")
    db.add(tn)
    db.flush()
    repo = Repository(tenant_id=tn.id, repo_full_name="acme/widgets", gh_installation_id=1,
                      base_branch="dev", prod_branch="main")
    db.add(repo)
    db.flush()
    emp = User(tenant_id=tn.id, role=UserRole.EMPLOYEE, display_name="Bob",
               platform="telegram", platform_user_id="emp-1")
    db.add(emp)
    db.flush()
    req = Request(tenant_id=tn.id, repo_id=repo.id, requester_user_id=emp.id, title="Add X",
                  status=status)
    db.add(req)
    db.flush()
    # 3 sự kiện kind khác nhau: 2 mới (msg, plan) + 1 cũ (system, 60 ngày trước)
    db.add(RequestEvent(request_id=req.id, kind=EventKind.MSG, direction=EventDirection.IN,
                        payload_json={"title": "Add X", "text": "please add X"},
                        created_at=_now()))
    db.add(RequestEvent(request_id=req.id, kind=EventKind.PLAN, direction=EventDirection.OUT,
                        payload_json={"summary": "plan summary"}, created_at=_now()))
    db.add(RequestEvent(request_id=req.id, kind=EventKind.SYSTEM, direction=EventDirection.OUT,
                        payload_json={"result": "old system note"},
                        created_at=_now() - timedelta(days=60)))
    db.commit()
    return tn, repo, req


def _login(client, uid=OWNER_UID):
    client.cookies.set(sess.COOKIE_NAME, sess.dumps(
        {"tok": "t", "login": "owner", "uid": uid, "name": "Owner"}, SECRET))


def _csrf(uid=OWNER_UID):
    return routes._csrf({"uid": uid}, Settings(_env_file=None, web_session_secret=SECRET))


def _count(db):
    return db.query(RequestEvent).count()


def test_lists_all_events_with_filter_bar(client, db):
    _seed(db)
    _login(client)
    r = client.get("/activity")
    assert r.status_code == 200
    # 3 sự kiện đều hiện + thanh lọc + nút xoá
    assert "plan summary" in r.text and "please add X" in r.text and "old system note" in r.text
    assert "/activity/clear" in r.text and "name='time'" in r.text


def test_filter_by_kind(client, db):
    _seed(db)
    _login(client)
    r = client.get("/activity?kind=plan")
    assert "plan summary" in r.text
    assert "please add X" not in r.text and "old system note" not in r.text


def test_filter_by_status_excludes_other_requests(client, db):
    _seed(db, status=RequestStatus.EXECUTING)
    _login(client)
    assert "plan summary" in client.get("/activity?status=executing").text
    # request đang EXECUTING ⇒ lọc theo merged_main không còn gì
    assert "plan summary" not in client.get("/activity?status=merged_main").text


def test_filter_by_time_excludes_old(client, db):
    _seed(db)
    _login(client)
    r = client.get("/activity?time=24h")
    assert "please add X" in r.text and "plan summary" in r.text
    assert "old system note" not in r.text  # sự kiện 60 ngày trước bị loại


def test_invalid_filter_falls_back_to_all(client, db):
    _seed(db)
    _login(client)
    r = client.get("/activity?kind=__nope__&status=bogus&time=99x")
    assert r.status_code == 200 and "plan summary" in r.text and "old system note" in r.text


def test_clear_respects_current_filter(client, db):
    _seed(db)
    _login(client)
    r = client.post("/activity/clear", follow_redirects=False,
                    data={"csrf": _csrf(), "kind": "plan"})
    assert r.status_code == 303 and r.headers["location"] == "/activity?kind=plan"
    # chỉ sự kiện kind=plan bị xoá; 2 cái còn lại nguyên
    assert _count(db) == 2
    assert db.query(RequestEvent).filter(RequestEvent.kind == EventKind.PLAN).count() == 0


def test_clear_by_time_only_removes_old(client, db):
    _seed(db)
    _login(client)
    # "older window" không có trực tiếp; lọc 24h sẽ xoá 2 cái mới, giữ cái cũ
    r = client.post("/activity/clear", follow_redirects=False,
                    data={"csrf": _csrf(), "time": "24h"})
    assert r.status_code == 303 and r.headers["location"] == "/activity?time=24h"
    assert _count(db) == 1
    assert db.query(RequestEvent).filter(RequestEvent.kind == EventKind.SYSTEM).count() == 1


def test_clear_all_when_no_filter(client, db):
    _seed(db)
    _login(client)
    r = client.post("/activity/clear", follow_redirects=False, data={"csrf": _csrf()})
    assert r.status_code == 303 and r.headers["location"] == "/activity"
    assert _count(db) == 0


def test_clear_requires_auth(client, db):
    _seed(db)
    r = client.post("/activity/clear", follow_redirects=False, data={"csrf": _csrf()})
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert _count(db) == 3  # không xoá


def test_clear_requires_csrf(client, db):
    _seed(db)
    _login(client)
    r = client.post("/activity/clear", follow_redirects=False, data={"csrf": "wrong"})
    assert r.status_code == 303 and r.headers["location"] == "/activity"
    assert _count(db) == 3  # không xoá


def test_clear_only_touches_own_workspace(client, db):
    _seed(db, uid=OTHER_UID)  # events thuộc owner khác
    _login(client, uid=OWNER_UID)
    r = client.post("/activity/clear", follow_redirects=False, data={"csrf": _csrf(OWNER_UID)})
    assert r.status_code == 303
    assert _count(db) == 3  # không đụng workspace người khác
