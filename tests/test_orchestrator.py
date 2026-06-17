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
