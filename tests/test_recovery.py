"""Tests recovery khởi động: request kẹt ở trạng thái CHẠY bị đóng + báo origin;
trạng thái CHỜ-user không đụng."""
import pytest
from sqlalchemy import select

from app.models import EventKind, Request, RequestEvent, RequestStatus, UserRole
from app.onboarding import add_repository, create_tenant, create_user
from app.config import Settings
from app.recovery import _build_adapter, close_interrupted, recover_interrupted_requests


def _seed(db):
    t = create_tenant(db, "Acme")
    repo = add_repository(db, t, "acme/widgets", 12345)
    emp = create_user(db, t, role=UserRole.EMPLOYEE, display_name="Bob")
    emp.platform_user_id = "emp-1"
    db.commit()
    return t, repo, emp


def _mkreq(db, t, repo, emp, status, **kw):
    req = Request(tenant_id=t.id, repo_id=repo.id, requester_user_id=emp.id,
                  title="x", body="x", status=status, **kw)
    db.add(req)
    db.commit()
    return req


def test_close_interrupted_only_running_states(db):
    t, repo, emp = _seed(db)
    new = _mkreq(db, t, repo, emp, RequestStatus.NEW)
    ana = _mkreq(db, t, repo, emp, RequestStatus.ANALYZING)
    exe = _mkreq(db, t, repo, emp, RequestStatus.EXECUTING)
    plan = _mkreq(db, t, repo, emp, RequestStatus.PLAN_REVIEW)   # CHỜ-user → giữ nguyên
    verify = _mkreq(db, t, repo, emp, RequestStatus.VERIFY)      # CHỜ-user → giữ nguyên

    closed = close_interrupted(db)

    assert {r.id for r in closed} == {new.id, ana.id, exe.id}
    for r in (new, ana, exe):
        db.refresh(r)
        assert r.status == RequestStatus.CANCELLED
    db.refresh(plan); db.refresh(verify)
    assert plan.status == RequestStatus.PLAN_REVIEW
    assert verify.status == RequestStatus.VERIFY
    # mỗi request bị đóng có 1 event SYSTEM ghi lý do
    evs = [e for e in db.scalars(select(RequestEvent)).all() if e.kind == EventKind.SYSTEM]
    assert len(evs) == 3
    assert all(e.payload_json.get("recovery") == "interrupted_by_restart" for e in evs)


@pytest.mark.asyncio
async def test_recover_notifies_origin(db):
    t, repo, emp = _seed(db)
    _mkreq(db, t, repo, emp, RequestStatus.EXECUTING,
           origin_platform="google_chat", origin_chat_id="spaces/AAA")
    _mkreq(db, t, repo, emp, RequestStatus.ANALYZING)   # không origin_chat_id → fallback pid

    sent = []

    class _Rec:
        async def send(self, dest, text, buttons=None):
            sent.append((dest, text))
        async def aclose(self):
            pass

    n = await recover_interrupted_requests(None, db=db, adapter_factory=lambda p: _Rec())

    assert n == 2
    dests = {d for d, _ in sent}
    assert "spaces/AAA" in dests          # group origin
    assert "emp-1" in dests               # fallback DM requester
    assert all("gián đoạn" in txt for _, txt in sent)


@pytest.mark.asyncio
async def test_recover_no_interrupted_noop(db):
    _seed(db)
    n = await recover_interrupted_requests(None, db=db, adapter_factory=lambda p: None)
    assert n == 0


def test_build_adapter_covers_all_channels():
    """_build_adapter phải dựng được adapter cho MỌI kênh đang dùng — nếu thiếu, deploy-gate
    sau restart không gửi được thông báo → request kẹt ở MERGED_DEV (orphan). Hồi quy: trước
    đây thiếu messenger/zalo nên request Messenger bị mồ côi sau mỗi lần redeploy."""
    s = Settings(
        telegram_bot_token="t", google_chat_enabled=True,
        messenger_enabled=True, messenger_page_access_token="pat",
        zalo_enabled=True, zalo_oa_access_token="z",
    )
    assert _build_adapter("telegram", s) is not None
    assert _build_adapter("google_chat", s) is not None
    assert _build_adapter("messenger", s) is not None
    assert _build_adapter("zalo", s) is not None
    assert _build_adapter("unknown", s) is None
    # Kênh tắt cờ → None (không dựng nhầm bằng token rỗng).
    assert _build_adapter("messenger", Settings(messenger_enabled=False)) is None
