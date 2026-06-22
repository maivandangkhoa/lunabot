"""Tests cancel_stuck_threads: chỉ huỷ request Google Chat group BLOCKING có origin_chat_id
dạng space cũ (chưa '/threads/'); request định tuyến mới hoặc kênh khác giữ nguyên; dry-run
không đụng DB."""
import pytest

from app.cancel_stuck_threads import cancel_stuck
from app.models import EventKind, RequestEvent, RequestStatus, UserRole
from app.onboarding import add_repository, create_tenant, create_user
from app.models import Request


def _seed(db):
    t = create_tenant(db, "Acme")
    repo = add_repository(db, t, "acme/widgets", 12345)
    emp = create_user(db, t, role=UserRole.EMPLOYEE, display_name="Bob")
    emp.platform_user_id = "users/emp-1"
    db.commit()
    return t, repo, emp


def _mkreq(db, t, repo, emp, status, **kw):
    req = Request(tenant_id=t.id, repo_id=repo.id, requester_user_id=emp.id,
                  title="x", body="x", status=status, **kw)
    db.add(req)
    db.commit()
    return req


class _Rec:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    async def send(self, dest, text, buttons=None):
        self.sent.append((dest, text))

    async def aclose(self):
        pass


@pytest.mark.asyncio
async def test_dryrun_does_not_touch_db(db):
    t, repo, emp = _seed(db)
    stuck = _mkreq(db, t, repo, emp, RequestStatus.ANALYZING,
                   origin_platform="google_chat", origin_is_group=True,
                   origin_chat_id="spaces/ROOM1")
    actions = await cancel_stuck(apply=False, db=db, github=None, adapter=_Rec())

    assert [a.request_id for a in actions] == [stuck.id]
    assert actions[0].applied is False
    db.refresh(stuck)
    assert stuck.status == RequestStatus.ANALYZING       # chưa đụng


@pytest.mark.asyncio
async def test_apply_cancels_only_old_space_group(db):
    t, repo, emp = _seed(db)
    stuck = _mkreq(db, t, repo, emp, RequestStatus.PLAN_REVIEW,
                   origin_platform="google_chat", origin_is_group=True,
                   origin_chat_id="spaces/ROOM1")                       # space cũ → huỷ
    new_thread = _mkreq(db, t, repo, emp, RequestStatus.PLAN_REVIEW,
                        origin_platform="google_chat", origin_is_group=True,
                        origin_chat_id="spaces/ROOM1/threads/T9")       # định tuyến mới → giữ
    dm = _mkreq(db, t, repo, emp, RequestStatus.CLARIFYING,
                origin_platform="google_chat", origin_is_group=False,
                origin_chat_id="spaces/DM1")                           # DM → giữ
    tele = _mkreq(db, t, repo, emp, RequestStatus.ANALYZING,
                  origin_platform="telegram", origin_is_group=True,
                  origin_chat_id="-1001")                              # kênh khác → giữ
    rec = _Rec()

    actions = await cancel_stuck(apply=True, db=db, github=None, adapter=rec)

    assert [a.request_id for a in actions] == [stuck.id]
    db.refresh(stuck); db.refresh(new_thread); db.refresh(dm); db.refresh(tele)
    assert stuck.status == RequestStatus.CANCELLED
    assert new_thread.status == RequestStatus.PLAN_REVIEW
    assert dm.status == RequestStatus.CLARIFYING
    assert tele.status == RequestStatus.ANALYZING
    assert rec.sent and rec.sent[0][0] == "spaces/ROOM1"   # báo đúng origin
    evs = [e for e in db.query(RequestEvent).all()
           if e.kind == EventKind.SYSTEM and e.request_id == stuck.id]
    assert len(evs) == 1 and evs[0].payload_json.get("action") == "cancel_stuck_thread"


@pytest.mark.asyncio
async def test_idempotent_second_run_finds_nothing(db):
    t, repo, emp = _seed(db)
    _mkreq(db, t, repo, emp, RequestStatus.EXECUTING,
           origin_platform="google_chat", origin_is_group=True,
           origin_chat_id="spaces/ROOM1")
    await cancel_stuck(apply=True, db=db, github=None, adapter=_Rec())
    actions = await cancel_stuck(apply=True, db=db, github=None, adapter=_Rec())
    assert actions == []
