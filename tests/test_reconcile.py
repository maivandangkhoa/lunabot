"""Tests reconcile request 'mồ côi': chỉ đóng request mà dev_merge_sha đã nằm trong
prod_branch; request chưa lên main giữ nguyên; dry-run không đụng DB."""
import pytest
from sqlalchemy import select

from app.models import EventKind, Request, RequestEvent, RequestStatus, UserRole
from app.onboarding import add_repository, create_tenant, create_user
from app.reconcile import reconcile_orphans


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


class _FakeGH:
    """commit_reachable_from theo dict sha→bool; ghi nhận nhánh bị xoá."""
    def __init__(self, reachable: dict[str, bool]):
        self.reachable = reachable
        self.deleted: list[str] = []

    async def commit_reachable_from(self, inst, repo, *, branch, sha):
        return self.reachable.get(sha, False)

    async def delete_branch(self, inst, repo, branch):
        self.deleted.append(branch)


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
    rel = _mkreq(db, t, repo, emp, RequestStatus.AWAIT_MANAGER, dev_merge_sha="aaa")
    gh = _FakeGH({"aaa": True})

    actions = await reconcile_orphans(None, gh, apply=False, db=db,
                                      adapter_factory=lambda p: _Rec())

    assert [a.verdict for a in actions] == ["released"]
    assert actions[0].applied is False
    db.refresh(rel)
    assert rel.status == RequestStatus.AWAIT_MANAGER     # chưa đụng
    assert gh.deleted == []


@pytest.mark.asyncio
async def test_apply_closes_only_released(db):
    t, repo, emp = _seed(db)
    rel = _mkreq(db, t, repo, emp, RequestStatus.AWAIT_MANAGER,
                 dev_merge_sha="aaa", branch_name="bot/req-1",
                 origin_platform="google_chat", origin_chat_id="spaces/AAA")
    pend = _mkreq(db, t, repo, emp, RequestStatus.MERGED_DEV, dev_merge_sha="bbb")
    gh = _FakeGH({"aaa": True, "bbb": False})
    rec = _Rec()

    actions = await reconcile_orphans(None, gh, apply=True, db=db,
                                      adapter_factory=lambda p: rec)

    verdicts = {a.request_id: a.verdict for a in actions}
    assert verdicts[rel.id] == "released" and verdicts[pend.id] == "pending"
    db.refresh(rel); db.refresh(pend)
    assert rel.status == RequestStatus.CLOSED            # đã release → đóng
    assert pend.status == RequestStatus.MERGED_DEV       # chưa lên main → giữ
    assert gh.deleted == ["bot/req-1"]                   # xoá đúng nhánh đã merge
    assert rec.sent and rec.sent[0][0] == "spaces/AAA"   # báo đúng origin group
    # ghi event SYSTEM thay vì Approval (không có người duyệt thật)
    evs = [e for e in db.scalars(select(RequestEvent)).all()
           if e.kind == EventKind.SYSTEM and e.request_id == rel.id]
    assert len(evs) == 1 and evs[0].payload_json.get("reconcile") == "already_on_main"


@pytest.mark.asyncio
async def test_skip_when_no_merge_sha(db):
    t, repo, emp = _seed(db)
    _mkreq(db, t, repo, emp, RequestStatus.AWAIT_MANAGER, dev_merge_sha=None)
    gh = _FakeGH({})

    actions = await reconcile_orphans(None, gh, apply=True, db=db,
                                      adapter_factory=lambda p: _Rec())

    assert actions[0].verdict.startswith("skipped")
