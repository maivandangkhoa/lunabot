"""Tests cổng production (prod_verify) — sau merge `main`: chờ CI + curl trang production
rồi mới kết luận.

Khẳng định: CI xanh + curl 200 → CLOSED + báo requester KÈM LINK production; CI đỏ → CLOSED
nhưng BÁO ĐỘNG requester + approver (KHÔNG auto-fix trên production); repo không có CI (no_ci)
→ giữ câu báo cũ 'đã merge và đóng'.
"""
import pytest

from app import post_deploy, prod_verify
from app.config import Settings
from app.models import Request, RequestStatus, UserRole
from app.onboarding import add_repository, create_tenant, create_user
from app.orchestrator import Orchestrator, cb
from app.prod_verify import verify_after_main_merge
from tests.conftest import FakeClaude, FakeGitHub, claude_json
from tests.test_post_deploy import DeployGitHub, _run

IMPL = '{"action":"implemented","summary":"fixed","branch":"x"}'


def _seed(db, **repo_settings):
    t = create_tenant(db, "Acme")
    repo = add_repository(db, t, "acme/widgets", 12345)
    repo.settings_json = {"prod_url": "https://sotaman.test", **repo_settings}
    emp = create_user(db, t, role=UserRole.EMPLOYEE, display_name="Bob")
    emp.platform_user_id = "emp-1"
    mgr = create_user(db, t, role=UserRole.MANAGER, display_name="Alice")
    mgr.platform_user_id = "mgr-1"
    db.commit()
    return t, repo, emp, mgr


def _merged_main_req(db, t, repo, emp, *, sha="mainsha"):
    req = Request(
        tenant_id=t.id, repo_id=repo.id, requester_user_id=emp.id, title="Thêm X",
        status=RequestStatus.MERGED_MAIN, report_json={"_main_merge_sha": sha},
        origin_platform="telegram", origin_chat_id=None, origin_is_group=False,
    )
    db.add(req)
    db.commit()
    return req


def _settings(**kw):
    base = dict(prod_verify_enabled=True, deploy_poll_interval_s=0,
                deploy_timeout_s=5, deploy_ci_grace_s=0)
    base.update(kw)
    return Settings(**base)


def _verify(db, req, github, fakes, **kw):
    return verify_after_main_merge(
        req.id, settings=_settings(), db=db, github=github,
        adapter=fakes["adapter"], git=fakes["git"], claude_run=FakeClaude([]), **kw)


@pytest.fixture(autouse=True)
def _ok_http(monkeypatch):
    """Mặc định curl trang production → 200. Test nào cần khác thì override."""
    async def ok(url):
        return True, "HTTP 200"
    monkeypatch.setattr(post_deploy, "_http_ok", ok)


@pytest.mark.asyncio
async def test_ci_green_and_curl_ok_closes_with_link(db, fakes):
    """CI xanh + trang production sống → đóng request, báo requester kèm LINK thật."""
    t, repo, emp, _ = _seed(db)
    req = _merged_main_req(db, t, repo, emp)
    gh = DeployGitHub([[_run("success")]])

    await _verify(db, req, gh, fakes)

    db.refresh(req)
    assert req.status == RequestStatus.CLOSED
    text = fakes["adapter"].sent[-1][1]
    assert "https://sotaman.test" in text and "production" in text


@pytest.mark.asyncio
async def test_ci_failed_alerts_requester_and_approvers(db, fakes):
    """CI đỏ → KHÔNG báo OK: cảnh báo requester + DM manager; KHÔNG auto-fix (không gọi Claude)."""
    t, repo, emp, mgr = _seed(db)
    req = _merged_main_req(db, t, repo, emp)
    gh = DeployGitHub([[_run("failure")]])
    claude = FakeClaude([])

    await verify_after_main_merge(
        req.id, settings=_settings(), db=db, github=gh,
        adapter=fakes["adapter"], git=fakes["git"], claude_run=claude)

    db.refresh(req)
    assert req.status == RequestStatus.CLOSED
    assert claude.calls == []                      # không đụng vào production
    targets = [s[0] for s in fakes["adapter"].sent]
    assert "emp-1" in targets and "mgr-1" in targets
    assert all("KHÔNG thành công" in s[1] for s in fakes["adapter"].sent)
    assert req.report_json["_prod_deploy"]["status"] == "failed"


@pytest.mark.asyncio
async def test_curl_fails_after_green_ci_alerts(db, fakes, monkeypatch):
    """CI xanh nhưng trang production không phản hồi → vẫn báo động, không báo 'đã lên'."""
    async def bad(url):
        return False, "HTTP 502"
    monkeypatch.setattr(post_deploy, "_http_ok", bad)
    t, repo, emp, _ = _seed(db)
    req = _merged_main_req(db, t, repo, emp)

    await _verify(db, req, DeployGitHub([[_run("success")]]), fakes)

    db.refresh(req)
    assert req.status == RequestStatus.CLOSED
    assert "KHÔNG thành công" in fakes["adapter"].sent[-1][1]


@pytest.mark.asyncio
async def test_no_ci_keeps_old_message(db, fakes):
    """Repo không chạy CI deploy → không có gì để chờ: câu báo cũ 'đã merge `main` và đóng'."""
    t, repo, emp, _ = _seed(db)
    req = _merged_main_req(db, t, repo, emp)

    await _verify(db, req, DeployGitHub([[]]), fakes)

    db.refresh(req)
    assert req.status == RequestStatus.CLOSED
    assert "đã merge" in fakes["adapter"].sent[-1][1]


@pytest.mark.asyncio
async def test_no_sha_falls_back_to_old_message(db, fakes):
    """Merge không trả sha → không poll được, giữ hành vi cũ thay vì treo."""
    t, repo, emp, _ = _seed(db)
    req = _merged_main_req(db, t, repo, emp, sha=None)

    await _verify(db, req, DeployGitHub([[_run("success")]]), fakes)

    db.refresh(req)
    assert req.status == RequestStatus.CLOSED
    assert "đã merge" in fakes["adapter"].sent[-1][1]


@pytest.mark.asyncio
async def test_prod_url_discovered_once_and_cached(db, fakes):
    """Không cấu hình prod_url → Claude dò 1 lần rồi cache vào settings_json.prod_url_auto."""
    t, repo, emp, _ = _seed(db)
    repo.settings_json = {}
    db.commit()
    req = _merged_main_req(db, t, repo, emp)
    claude = FakeClaude([claude_json('{"prod_url":"https://sotaman.web.app"}')])

    await verify_after_main_merge(
        req.id, settings=_settings(), db=db, github=DeployGitHub([[_run("success")]]),
        adapter=fakes["adapter"], git=fakes["git"], claude_run=claude)

    db.refresh(repo)
    assert repo.settings_json["prod_url_auto"] == "https://sotaman.web.app"
    assert "https://sotaman.web.app" in fakes["adapter"].sent[-1][1]


@pytest.mark.asyncio
async def test_wrong_status_is_noop(db, fakes):
    """Request đã đổi state ở nơi khác (vd reconcile đóng) → task nền bỏ qua, không gửi gì."""
    t, repo, emp, _ = _seed(db)
    req = _merged_main_req(db, t, repo, emp)
    req.status = RequestStatus.CLOSED
    db.commit()

    await _verify(db, req, DeployGitHub([[_run("success")]]), fakes)

    assert fakes["adapter"].sent == []


@pytest.mark.asyncio
async def test_gate_off_closes_immediately(db, fakes):
    """Cổng tắt (mặc định test) → hợp đồng cũ giữ nguyên: merge main xong đóng & báo ngay."""
    t, repo, emp, mgr = _seed(db)
    req = Request(tenant_id=t.id, repo_id=repo.id, requester_user_id=emp.id, title="X",
                  status=RequestStatus.AWAIT_MANAGER, pr_number=None, branch_name="bot/req-1",
                  origin_platform="telegram", origin_is_group=False)
    db.add(req)
    db.commit()
    orch = Orchestrator(db, fakes["adapter"], github=FakeGitHub(),
                        claude_run=FakeClaude([]), git=fakes["git"])

    await orch.handle_callback(req, mgr, cb("mgr_approve", req.id))

    db.refresh(req)
    assert req.status == RequestStatus.CLOSED


@pytest.mark.asyncio
async def test_gate_on_waits_before_closing(db, fakes, prod_gate_on):
    """Cổng bật: merge main xong request Ở LẠI MERGED_MAIN + báo 'đang chờ triển khai',
    và sha merge được ghi lại để task nền poll."""
    t, repo, emp, mgr = _seed(db)
    req = Request(tenant_id=t.id, repo_id=repo.id, requester_user_id=emp.id, title="X",
                  status=RequestStatus.AWAIT_MANAGER, branch_name="bot/req-1",
                  origin_platform="telegram", origin_is_group=False)
    db.add(req)
    db.commit()
    gh = DeployGitHub([[]])   # task nền (nếu chạy) không có CI → vô hại
    orch = Orchestrator(db, fakes["adapter"], github=gh,
                        claude_run=FakeClaude([]), git=fakes["git"])

    await orch.handle_callback(req, mgr, cb("mgr_approve", req.id))

    db.refresh(req)
    assert req.status == RequestStatus.MERGED_MAIN
    assert prod_verify.main_merge_sha(req)          # sha đã ghi để poll
    assert "chờ" in fakes["adapter"].sent[-1][1]


@pytest.mark.asyncio
async def test_recovery_rekicks_merged_main(db, monkeypatch):
    """Restart giữa lúc chờ deploy production → startup re-poll request kẹt ở MERGED_MAIN."""
    from app import recovery

    t, repo, emp, _ = _seed(db)
    req = _merged_main_req(db, t, repo, emp)
    kicked: list[int] = []

    async def fake_verify(req_id, **kw):
        kicked.append(req_id)

    monkeypatch.setattr(prod_verify, "verify_after_main_merge", fake_verify)
    n = await recovery.rekick_pending_deploys(_settings(), db=db)
    assert n == 1
