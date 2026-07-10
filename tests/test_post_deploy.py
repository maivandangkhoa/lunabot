"""Tests deploy-gate (post_deploy) — sau merge dev: chờ CI + curl trang dev rồi mới mời manager.

Inject db/adapter/github/claude/git giả lập. Khẳng định: CI xanh + curl 200 → AWAIT_MANAGER +
báo 'đã deploy + test ổn'; lỗi → auto-fix (fix-forward) tới khi xanh; hết vòng → về VERIFY,
KHÔNG mời manager (đúng khiếu nại gốc: không báo OK khi build lỗi).
"""
import pytest

from app import post_deploy
from app.config import Settings
from app.models import Request, RequestStatus, UserRole
from app.onboarding import add_repository, create_tenant, create_user
from app.orchestrator import Orchestrator, cb
from app.post_deploy import verify_after_dev_merge
from tests.conftest import FakeClaude, FakeGitHub, claude_json

IMPL = '{"action":"implemented","summary":"fixed","branch":"x"}'


def _run(conclusion, *, status="completed", rid=1, name="deploy"):
    return {"id": rid, "name": name, "status": status, "conclusion": conclusion,
            "html_url": f"https://gh/run/{rid}", "path": ".github/workflows/deploy.yml"}


class DeployGitHub(FakeGitHub):
    """FakeGitHub + Actions API: trả lần lượt từng đợt runs (đợt cuối lặp lại)."""

    def __init__(self, runs_per_poll):
        super().__init__()
        self.runs_per_poll = list(runs_per_poll)
        self.poll_calls = 0

    async def list_workflow_runs(self, installation_id, repo_full_name, *, head_sha):
        idx = min(self.poll_calls, len(self.runs_per_poll) - 1)
        self.poll_calls += 1
        return self.runs_per_poll[idx]

    async def run_failure_summary(self, installation_id, repo_full_name, run_id):
        return "- job 'build' → failure (step lỗi: tsc)"


def _seed(db):
    t = create_tenant(db, "Acme")
    repo = add_repository(db, t, "acme/widgets", 12345)
    repo.settings_json = {"dev_url": "https://sotaman-dev.test"}
    emp = create_user(db, t, role=UserRole.EMPLOYEE, display_name="Bob")
    emp.platform_user_id = "emp-1"
    mgr = create_user(db, t, role=UserRole.MANAGER, display_name="Alice")
    mgr.platform_user_id = "mgr-1"
    db.commit()
    return t, repo, emp, mgr


def _merged_req(db, t, repo, emp, *, sha="sha1"):
    req = Request(
        tenant_id=t.id, repo_id=repo.id, requester_user_id=emp.id, title="Thêm X",
        status=RequestStatus.MERGED_DEV, dev_merge_sha=sha, pr_number=7,
        branch_name="bot/req-1", claude_session_id="s1",
        origin_platform="telegram", origin_chat_id=None, origin_is_group=False,
    )
    db.add(req)
    db.commit()
    return req


def _settings(**kw):
    base = dict(dev_verify_enabled=True, dev_verify_max_rounds=1,
                deploy_poll_interval_s=0, deploy_timeout_s=5, deploy_ci_grace_s=0)
    base.update(kw)
    return Settings(**base)


def _verify(db, req, github, fakes, *, claude=None, settings=None):
    return verify_after_dev_merge(
        req.id, settings=settings or _settings(), db=db, github=github,
        adapter=fakes["adapter"], git=fakes["git"],
        claude_run=claude or FakeClaude([]))


@pytest.fixture(autouse=True)
def _ok_http(monkeypatch):
    """Mặc định curl trang dev → 200. Test nào cần khác thì override."""
    async def ok(url):
        return True, "HTTP 200"
    monkeypatch.setattr(post_deploy, "_http_ok", ok)


@pytest.mark.asyncio
async def test_ci_green_and_curl_ok_invites_uat(db, fakes):
    """Preview-first: CI xanh + curl 200 → mời REQUESTER kiểm thử trên URL dev thật (VERIFY),
    CHƯA mời manager (đợi requester bấm Đạt)."""
    t, repo, emp, mgr = _seed(db)
    req = _merged_req(db, t, repo, emp)
    gh = DeployGitHub([[_run("success")]])

    await _verify(db, req, gh, fakes)

    assert req.status == RequestStatus.VERIFY
    assert any("sotaman-dev.test" in s[1] for s in fakes["adapter"].sent)  # link dev cho requester
    assert not any(s[0] == "mgr-1" for s in fakes["adapter"].sent)         # chưa mời manager


@pytest.mark.asyncio
async def test_admin_only_tenant_is_invited(db, fakes):
    """Tenant không có manager nhưng có admin → admin được mời (admin cũng có quyền duyệt)."""
    t = create_tenant(db, "AdminCo")
    repo = add_repository(db, t, "adminco/widgets", 12345)
    repo.settings_json = {"dev_url": "https://sotaman-dev.test"}
    emp = create_user(db, t, role=UserRole.EMPLOYEE, display_name="Bob")
    emp.platform_user_id = "emp-1"
    admin = create_user(db, t, role=UserRole.ADMIN, display_name="Root")
    admin.platform_user_id = "admin-1"
    db.commit()
    req = _merged_req(db, t, repo, emp)
    gh = DeployGitHub([[_run("success")]])

    await _verify(db, req, gh, fakes)
    assert req.status == RequestStatus.VERIFY                     # requester UAT trước
    # Requester duyệt → admin (cũng có quyền duyệt) được mời.
    orch = Orchestrator(db, fakes["adapter"], github=gh,
                        claude_run=FakeClaude([]), git=fakes["git"])
    await orch.handle_callback(req, emp, cb("verify_ok", req.id))

    assert req.status == RequestStatus.AWAIT_MANAGER
    assert any(s[0] == "admin-1" for s in fakes["adapter"].sent)  # admin được mời duyệt


@pytest.mark.asyncio
async def test_curl_fails_does_not_invite_manager(db, fakes, monkeypatch):
    t, repo, emp, mgr = _seed(db)
    req = _merged_req(db, t, repo, emp)
    gh = DeployGitHub([[_run("success")]])

    async def bad(url):
        return False, "HTTP 502"
    monkeypatch.setattr(post_deploy, "_http_ok", bad)

    await _verify(db, req, gh, fakes, settings=_settings(dev_verify_max_rounds=0))

    assert req.status == RequestStatus.VERIFY          # về cho người quyết, KHÔNG mời manager
    assert req.pr_number is None                        # reset để sửa thủ công tạo PR mới
    assert not any(s[0] == "mgr-1" for s in fakes["adapter"].sent)
    assert any("CHƯA báo manager" in s[1] for s in fakes["adapter"].sent)


@pytest.mark.asyncio
async def test_ci_fail_then_autofix_succeeds(db, fakes):
    t, repo, emp, mgr = _seed(db)
    req = _merged_req(db, t, repo, emp)
    # Đợt 1 build lỗi → auto-fix → đợt 2 build xanh.
    gh = DeployGitHub([[_run("failure", rid=1)], [_run("success", rid=2)]])
    claude = FakeClaude([claude_json(IMPL, "s2")])

    await _verify(db, req, gh, fakes, claude=claude)

    assert req.status == RequestStatus.VERIFY           # autofix xanh → mời requester UAT
    assert len(gh.merged) == 1                          # đã tạo+merge PR fix mới
    assert req.dev_merge_sha == "mergesha7"             # sha merge của PR fix (PR mới #7)
    assert req.branch_name == "bot/req-1-fix1"
    assert any("tự sửa lại" in s[1] for s in fakes["adapter"].sent)


@pytest.mark.asyncio
async def test_ci_fail_exhausts_rounds_goes_to_verify(db, fakes):
    t, repo, emp, mgr = _seed(db)
    req = _merged_req(db, t, repo, emp)
    gh = DeployGitHub([[_run("failure")]])             # luôn lỗi
    claude = FakeClaude([claude_json(IMPL, "s2")])     # 1 vòng fix

    await _verify(db, req, gh, fakes, claude=claude,
                  settings=_settings(dev_verify_max_rounds=1))

    assert req.status == RequestStatus.VERIFY
    assert not any(s[0] == "mgr-1" for s in fakes["adapter"].sent)
    assert any("CHƯA báo manager" in s[1] for s in fakes["adapter"].sent)


@pytest.mark.asyncio
async def test_autofix_claude_no_change_gives_up(db, fakes):
    t, repo, emp, mgr = _seed(db)
    req = _merged_req(db, t, repo, emp)
    gh = DeployGitHub([[_run("failure")]])
    claude = FakeClaude([claude_json(IMPL, "s2")])
    fakes["git"].has_changes = False                   # Claude không sửa gì → fix thất bại

    await _verify(db, req, gh, fakes, claude=claude)

    assert req.status == RequestStatus.VERIFY
    assert len(gh.merged) == 0                          # không merge PR rỗng
    assert any("vẫn chưa được" in s[1] for s in fakes["adapter"].sent)


@pytest.mark.asyncio
async def test_auto_discovers_dev_url_when_only_gate_flag(db, fakes):
    """Chỉ bật cờ deploy_gate (không nhập dev_url) → bot tự dò từ repo, cache lại, curl rồi mời requester UAT kèm link."""
    t = create_tenant(db, "Acme")
    repo = add_repository(db, t, "acme/widgets", 12345)
    repo.settings_json = {"deploy_gate": True}          # bật cổng, KHÔNG nhập dev_url
    emp = create_user(db, t, role=UserRole.EMPLOYEE, display_name="Bob")
    emp.platform_user_id = "emp-1"
    mgr = create_user(db, t, role=UserRole.MANAGER, display_name="Alice")
    mgr.platform_user_id = "mgr-1"
    db.commit()
    req = _merged_req(db, t, repo, emp)
    gh = DeployGitHub([[_run("success")]])
    # Claude read-only dò ra URL từ .firebaserc/workflow.
    claude = FakeClaude([claude_json('{"dev_url":"https://sotaman-dev.web.app"}', "s9")])

    await _verify(db, req, gh, fakes, claude=claude)

    assert req.status == RequestStatus.VERIFY
    assert repo.settings_json.get("dev_url_auto") == "https://sotaman-dev.web.app"  # đã cache
    assert any("sotaman-dev.web.app" in s[1] for s in fakes["adapter"].sent)  # link dò được gửi requester


def test_dev_verify_configured_default_true_optout_false(db):
    from app import post_deploy as pd
    t = create_tenant(db, "Acme")
    r = add_repository(db, t, "acme/x", 1)
    r.settings_json = {}
    assert pd.dev_verify_configured(r) is True          # MẶC ĐỊNH bật cho mọi repo
    r.settings_json = {"deploy_gate": False}
    assert pd.dev_verify_configured(r) is False          # opt-out tường minh
    r.settings_json = {"deploy_gate": True}
    assert pd.dev_verify_configured(r) is True


@pytest.mark.asyncio
async def test_no_ci_repo_invites_uat(db, fakes):
    """Gate bật mặc định nhưng repo KHÔNG có workflow nào cho commit → no_ci → mời requester UAT
    (không có link deploy), CHƯA mời manager."""
    t, repo, emp, mgr = _seed(db)
    repo.settings_json = {}                              # gate mặc định bật, không cấu hình gì
    db.commit()
    req = _merged_req(db, t, repo, emp)
    gh = DeployGitHub([[]])                              # không có run nào cho sha

    await _verify(db, req, gh, fakes)

    assert req.status == RequestStatus.VERIFY
    assert not any(s[0] == "mgr-1" for s in fakes["adapter"].sent)  # chưa mời manager


@pytest.mark.asyncio
async def test_optout_repo_invites_manager_immediately(db, fakes):
    """Repo opt-out (deploy_gate=false): verify_ok → mời manager ngay (đồng bộ, không spawn gate)."""
    t = create_tenant(db, "Beta")
    repo = add_repository(db, t, "beta/app", 999)
    repo.settings_json = {"deploy_gate": False}
    emp = create_user(db, t, role=UserRole.EMPLOYEE, display_name="Bob")
    emp.platform_user_id = "emp-1"
    mgr = create_user(db, t, role=UserRole.MANAGER, display_name="Alice")
    mgr.platform_user_id = "mgr-1"
    db.commit()
    req = _merged_req(db, t, repo, emp)
    req.status = RequestStatus.VERIFY                   # đặt lại để chạy verify_ok đúng FSM
    db.commit()

    claude = FakeClaude([])
    orch = Orchestrator(db, fakes["adapter"], github=fakes["github"],
                        claude_run=claude, git=fakes["git"])
    await orch.handle_callback(req, emp, cb("verify_ok", req.id))

    assert req.status == RequestStatus.AWAIT_MANAGER
    assert any(s[0] == "mgr-1" for s in fakes["adapter"].sent)


@pytest.mark.asyncio
async def test_notify_managers_dm_each_in_own_language(db, fakes):
    """Requester 'en', 2 approver 'ko'/'vi' → mỗi DM compose theo ngôn ngữ NGƯỜI NHẬN,
    không phải ngôn ngữ requester đang nằm trong contextvar."""
    t, repo, emp, mgr = _seed(db)
    emp.language = "en"
    mgr.language = "ko"
    admin = create_user(db, t, role=UserRole.ADMIN, display_name="Chief")
    admin.platform_user_id = "admin-9"
    admin.language = "vi"
    db.commit()
    req = _merged_req(db, t, repo, emp)
    orch = Orchestrator(db, fakes["adapter"], github=fakes["github"],
                        claude_run=FakeClaude([]), git=fakes["git"])

    await post_deploy.notify_managers(orch, req, repo)

    mgr_msg = next(s for s in fakes["adapter"].sent if s[0] == "mgr-1")
    admin_msg = next(s for s in fakes["adapter"].sent if s[0] == "admin-9")
    assert "머지" in mgr_msg[1] or "승인" in mgr_msg[1]        # tiếng Hàn
    assert "sẵn sàng merge" in admin_msg[1]                     # tiếng Việt
    # Nút cũng theo ngôn ngữ từng người.
    assert any("머지 승인" in b.text for row in mgr_msg[2] for b in row)
    assert any("Cho merge" in b.text for row in admin_msg[2] for b in row)


@pytest.mark.asyncio
async def test_notify_managers_group_uses_requester_language(db, fakes):
    t, repo, emp, mgr = _seed(db)
    emp.language = "en"
    mgr.language = "ko"
    db.commit()
    req = _merged_req(db, t, repo, emp)
    req.origin_is_group = True
    req.origin_chat_id = "group-1"
    db.commit()
    orch = Orchestrator(db, fakes["adapter"], github=fakes["github"],
                        claude_run=FakeClaude([]), git=fakes["git"])

    await post_deploy.notify_managers(orch, req, repo)

    g = next(s for s in fakes["adapter"].sent if s[0] == "group-1")
    assert "ready to merge" in g[1]                             # tiếng Anh (requester)
