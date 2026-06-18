"""Tests Orchestrator — vòng đời FSM đầy đủ + nhánh clarify + chặn quyền manager.

Side-effect (claude/git/github/adapter) dùng fake (conftest). Khẳng định: status đúng
từng bước, events/approvals được ghi, manager được thông báo, non-manager bị chặn.
"""
import pytest

from app.claude_runner import ClaudeResult
from app.models import ApprovalDecision, RequestStatus, UserRole
from app.onboarding import add_repository, create_tenant, create_user
from app.orchestrator import Orchestrator, cb
from tests.conftest import FakeClaude, claude_json

PLAN = '{"action":"plan","summary":"do x","steps":["a","b"],"risk":"low"}'
IMPL = '{"action":"implemented","summary":"done","branch":"bot/req-1"}'
CLARIFY = '{"action":"clarify","questions":["DB nào?"]}'


def _seed(db):
    t = create_tenant(db, "Acme")
    repo = add_repository(db, t, "acme/widgets", 12345)
    repo.settings_json = {"deploy_gate": False}  # test FSM thuần; deploy-gate test riêng ở test_post_deploy
    emp = create_user(db, t, role=UserRole.EMPLOYEE, display_name="Bob")
    emp.platform_user_id = "emp-1"
    mgr = create_user(db, t, role=UserRole.MANAGER, display_name="Alice")
    mgr.platform_user_id = "mgr-1"
    db.commit()
    return t, repo, emp, mgr


def _orch(db, fakes, claude):
    return Orchestrator(db, fakes["adapter"], github=fakes["github"],
                        claude_run=claude, git=fakes["git"])


@pytest.mark.asyncio
async def test_full_happy_path(db, fakes, tmp_path):
    t, repo, emp, mgr = _seed(db)
    claude = FakeClaude([claude_json(PLAN, "s1"), claude_json(IMPL, "s2")])
    orch = _orch(db, fakes, claude)
    orch.workspace = tmp_path

    req = await orch.create_request(repo, emp, "Thêm rate limit", "chi tiết")
    assert req.status == RequestStatus.PLAN_REVIEW
    assert req.claude_session_id == "s1"
    # Plan gửi cho requester kèm nút Confirm.
    assert any("Kế hoạch" in s[1] for s in fakes["adapter"].sent)

    await orch.handle_callback(req, emp, cb("confirm", req.id))
    assert req.status == RequestStatus.VERIFY
    assert req.pr_number == 7 and "pull/7" in req.pr_url
    assert fakes["github"].created_prs[0]["base"] == "dev"

    await orch.handle_callback(req, emp, cb("verify_ok", req.id))
    assert req.status == RequestStatus.AWAIT_MANAGER
    assert 7 in fakes["github"].merged  # PR vào dev đã merge
    # Manager được thông báo.
    assert any(s[0] == "mgr-1" for s in fakes["adapter"].sent)

    await orch.handle_callback(req, mgr, cb("mgr_approve", req.id))
    assert req.status == RequestStatus.CLOSED
    assert any(a.decision == ApprovalDecision.APPROVED for a in req.approvals)
    # Nhánh feature đã merge xong → bị dọn (không tích tụ bot/req-* trên repo khách).
    assert req.branch_name in fakes["github"].deleted_branches


@pytest.mark.asyncio
async def test_group_request_notifies_managers_in_group(db, fakes, tmp_path):
    """Request đến từ group: reply + yêu cầu duyệt manager đăng CÔNG KHAI trong group, không DM."""
    t, repo, emp, mgr = _seed(db)
    claude = FakeClaude([claude_json(PLAN, "s1"), claude_json(IMPL, "s2")])
    orch = _orch(db, fakes, claude)
    orch.workspace = tmp_path

    req = await orch.create_request(repo, emp, "X", None,
                                    chat_id="-100", platform="telegram", is_group=True)
    await orch.handle_callback(req, emp, cb("confirm", req.id), reply_to="-100")
    await orch.handle_callback(req, emp, cb("verify_ok", req.id), reply_to="-100")
    assert req.status == RequestStatus.AWAIT_MANAGER
    # Yêu cầu duyệt đăng vào group; KHÔNG DM mgr-1.
    assert any(s[0] == "-100" and "sẵn sàng merge" in s[1] for s in fakes["adapter"].sent)
    assert not any(s[0] == "mgr-1" for s in fakes["adapter"].sent)


@pytest.mark.asyncio
async def test_ownership_guard_blocks_other_user(db, fakes, tmp_path):
    """Trong group, user khác bấm nút của request không phải của mình → bị chặn."""
    t, repo, emp, mgr = _seed(db)
    other = create_user(db, t, role=UserRole.EMPLOYEE, display_name="Eve")
    other.platform_user_id = "emp-2"
    db.commit()
    claude = FakeClaude([claude_json(PLAN, "s1")])
    orch = _orch(db, fakes, claude)
    orch.workspace = tmp_path

    req = await orch.create_request(repo, emp, "X", None,
                                    chat_id="-100", platform="telegram", is_group=True)
    assert req.status == RequestStatus.PLAN_REVIEW
    await orch.handle_callback(req, other, cb("confirm", req.id), reply_to="-100")
    assert req.status == RequestStatus.PLAN_REVIEW  # không đổi
    assert any("không phải" in s[1].lower() for s in fakes["adapter"].sent)


@pytest.mark.asyncio
async def test_double_click_manager_blocked(db, fakes, tmp_path):
    """Nhiều manager trong group: người thứ 2 bấm duyệt sau khi đã xử lý → báo 'đã được xử lý'."""
    t, repo, emp, mgr = _seed(db)
    mgr2 = create_user(db, t, role=UserRole.MANAGER, display_name="Mike")
    mgr2.platform_user_id = "mgr-2"
    db.commit()
    claude = FakeClaude([claude_json(PLAN, "s1"), claude_json(IMPL, "s2")])
    orch = _orch(db, fakes, claude)
    orch.workspace = tmp_path

    req = await orch.create_request(repo, emp, "X", None,
                                    chat_id="-100", platform="telegram", is_group=True)
    await orch.handle_callback(req, emp, cb("confirm", req.id), reply_to="-100")
    await orch.handle_callback(req, emp, cb("verify_ok", req.id), reply_to="-100")
    await orch.handle_callback(req, mgr, cb("mgr_approve", req.id), reply_to="-100")
    assert req.status == RequestStatus.CLOSED
    await orch.handle_callback(req, mgr2, cb("mgr_approve", req.id), reply_to="-100")
    assert any("đã được xử lý" in s[1] for s in fakes["adapter"].sent)


@pytest.mark.asyncio
async def test_clarify_then_plan(db, fakes, tmp_path):
    t, repo, emp, mgr = _seed(db)
    claude = FakeClaude([claude_json(CLARIFY, "s1"), claude_json(PLAN, "s1")])
    orch = _orch(db, fakes, claude)
    orch.workspace = tmp_path

    req = await orch.create_request(repo, emp, "Cải tiến gì đó", None)
    assert req.status == RequestStatus.CLARIFYING
    assert any("làm rõ" in s[1].lower() or "❓" in s[1] for s in fakes["adapter"].sent)

    await orch.handle_message(req, emp, "Dùng Postgres")
    assert req.status == RequestStatus.PLAN_REVIEW


@pytest.mark.asyncio
async def test_non_manager_cannot_approve(db, fakes, tmp_path):
    t, repo, emp, mgr = _seed(db)
    claude = FakeClaude([claude_json(PLAN, "s1"), claude_json(IMPL, "s2")])
    orch = _orch(db, fakes, claude)
    orch.workspace = tmp_path

    req = await orch.create_request(repo, emp, "X", None)
    await orch.handle_callback(req, emp, cb("confirm", req.id))
    await orch.handle_callback(req, emp, cb("verify_ok", req.id))
    assert req.status == RequestStatus.AWAIT_MANAGER

    # employee bấm duyệt → bị chặn, status không đổi.
    await orch.handle_callback(req, emp, cb("mgr_approve", req.id))
    assert req.status == RequestStatus.AWAIT_MANAGER
    assert any("Chỉ manager" in s[1] for s in fakes["adapter"].sent)


@pytest.mark.asyncio
async def test_claude_no_json_relays_and_clarifies(db, fakes, tmp_path):
    t, repo, emp, mgr = _seed(db)
    # Claude chạy OK nhưng trả lời câu hỏi, không kèm JSON.
    claude = FakeClaude([ClaudeResult(ok=True, result="Chức năng WFH vẫn hoạt động.", session_id="s1")])
    orch = _orch(db, fakes, claude)
    orch.workspace = tmp_path

    req = await orch.create_request(repo, emp, "WFH còn chạy không?", None)
    # Relay nội dung + chuyển CLARIFYING (không chết cứng).
    assert req.status == RequestStatus.CLARIFYING
    assert any("WFH vẫn hoạt động" in s[1] for s in fakes["adapter"].sent)


@pytest.mark.asyncio
async def test_claude_hard_error_needs_human(db, fakes, tmp_path):
    t, repo, emp, mgr = _seed(db)
    # Claude lỗi hạ tầng (ok=False).
    claude = FakeClaude([ClaudeResult(ok=False, result="❌ Claude lỗi (code 1)", session_id="s1")])
    orch = _orch(db, fakes, claude)
    orch.workspace = tmp_path

    req = await orch.create_request(repo, emp, "X", None)
    assert req.status == RequestStatus.ANALYZING
    assert any("can thiệp" in s[1] for s in fakes["adapter"].sent)


@pytest.mark.asyncio
async def test_manager_reject_reverts_dev_and_cleans(db, fakes, tmp_path):
    """Manager từ chối ở AWAIT_MANAGER → revert dev, đóng PR, xoá nhánh."""
    t, repo, emp, mgr = _seed(db)
    claude = FakeClaude([claude_json(PLAN, "s1"), claude_json(IMPL, "s2")])
    orch = _orch(db, fakes, claude)
    orch.workspace = tmp_path

    req = await orch.create_request(repo, emp, "Thêm X", "chi tiết")
    await orch.handle_callback(req, emp, cb("confirm", req.id))
    await orch.handle_callback(req, emp, cb("verify_ok", req.id))
    assert req.status == RequestStatus.AWAIT_MANAGER
    assert req.dev_merge_sha == "mergesha7"  # SHA merge vào dev được lưu

    await orch.handle_callback(req, mgr, cb("mgr_reject", req.id))
    assert req.status == RequestStatus.CANCELLED
    assert any(a.decision == ApprovalDecision.REJECTED for a in req.approvals)
    assert fakes["git"].reverted == "mergesha7"            # đã revert dev
    assert req.pr_number in fakes["github"].closed_prs      # PR đã đóng
    assert req.branch_name in fakes["github"].deleted_branches  # nhánh đã xoá


@pytest.mark.asyncio
async def test_cancel_at_verify_closes_pr_no_revert(db, fakes, tmp_path):
    """Huỷ ở VERIFY (chưa merge dev) → đóng PR + xoá nhánh, KHÔNG revert dev."""
    t, repo, emp, mgr = _seed(db)
    claude = FakeClaude([claude_json(PLAN, "s1"), claude_json(IMPL, "s2")])
    orch = _orch(db, fakes, claude)
    orch.workspace = tmp_path

    req = await orch.create_request(repo, emp, "Thêm X", "chi tiết")
    await orch.handle_callback(req, emp, cb("confirm", req.id))
    assert req.status == RequestStatus.VERIFY

    await orch.handle_callback(req, emp, cb("cancel", req.id))
    assert req.status == RequestStatus.CANCELLED
    assert req.pr_number in fakes["github"].closed_prs
    assert req.branch_name in fakes["github"].deleted_branches
    assert getattr(fakes["git"], "reverted", None) is None  # dev chưa bị đụng
