"""Tests Orchestrator — vòng đời FSM đầy đủ + nhánh clarify + chặn quyền manager.

Side-effect (claude/git/github/adapter) dùng fake (conftest). Khẳng định: status đúng
từng bước, events/approvals được ghi, manager được thông báo, non-manager bị chặn.
"""
import pytest

from app.claude_runner import ClaudeResult
from app.models import ApprovalDecision, Request, RequestStatus, UserRole
from app.onboarding import add_repository, create_tenant, create_user
from app.orchestrator import Orchestrator, cb
from tests.conftest import FakeClaude, FakeGit, claude_json

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


IMPL_RICH = (
    '{"action":"implemented","summary":"done","branch":"bot/req-1",'
    '"change_type":"bug_fix","root_cause":"thiếu validate",'
    '"changes":["Sửa nút lưu"],"self_test":["✓ Lưu thành công"],"self_test_conclusion":"PASS"}'
)


@pytest.mark.asyncio
async def test_verify_handoff_is_business_and_persists_report(db, fakes, tmp_path):
    """Bàn giao VERIFY: tin cho người tạo yêu cầu là báo cáo nghiệp vụ (KHÔNG lộ PR/diff),
    và gói báo cáo được lưu vào report_json để mời manager về sau."""
    t, repo, emp, mgr = _seed(db)
    claude = FakeClaude([claude_json(PLAN, "s1"), claude_json(IMPL_RICH, "s2")])
    orch = _orch(db, fakes, claude)
    orch.workspace = tmp_path

    req = await orch.create_request(repo, emp, "Sửa nút lưu", "chi tiết")
    await orch.handle_callback(req, emp, cb("confirm", req.id))

    assert req.status == RequestStatus.VERIFY
    # report_json lưu từ tín hiệu Claude + thống kê diff (FakeGit.diff_summary).
    assert req.report_json["change_type"] == "bug_fix"
    assert req.report_json["self_test_conclusion"] == "PASS"
    assert req.report_json["diff"]["files_changed"] == 1
    # Tin bàn giao là báo cáo tự kiểm thử nghiệp vụ — KHÔNG lộ PR/diff cho người dùng cuối.
    verify_msg = fakes["adapter"].sent[-1][1]
    assert "Sửa nút lưu" in verify_msg and "tự kiểm thử" in verify_msg.lower()
    assert "pull/" not in verify_msg and "src/app.py" not in verify_msg


@pytest.mark.asyncio
async def test_manager_packet_sent_at_approval(db, fakes, tmp_path):
    """Khi mời duyệt, manager nhận gói 10.x (có diff/PR) — nơi DUY NHẤT lộ kỹ thuật."""
    t, repo, emp, mgr = _seed(db)
    claude = FakeClaude([claude_json(PLAN, "s1"), claude_json(IMPL_RICH, "s2")])
    orch = _orch(db, fakes, claude)
    orch.workspace = tmp_path

    req = await orch.create_request(repo, emp, "Sửa nút lưu", "chi tiết")
    await orch.handle_callback(req, emp, cb("confirm", req.id))
    await orch.handle_callback(req, emp, cb("verify_ok", req.id))

    mgr_msg = next(s[1] for s in fakes["adapter"].sent if s[0] == "mgr-1")
    assert "sẵn sàng merge" in mgr_msg
    assert "pull/" in mgr_msg                    # diff (PR) cho manager
    assert "src/app.py" in mgr_msg               # danh sách file
    assert "Sửa lỗi" in mgr_msg                   # change_type đã dịch


@pytest.mark.asyncio
async def test_execute_failure_message_has_no_tech_detail(db, fakes, tmp_path):
    """Lỗi thực thi: tin cho người dùng cuối KHÔNG kèm stderr/log kỹ thuật."""
    t, repo, emp, mgr = _seed(db)
    bad = ClaudeResult(ok=False, result="Traceback: fatal error at db.py:42", session_id="s2")
    claude = FakeClaude([claude_json(PLAN, "s1"), bad])
    orch = _orch(db, fakes, claude)
    orch.workspace = tmp_path

    req = await orch.create_request(repo, emp, "X", "y")
    await orch.handle_callback(req, emp, cb("confirm", req.id))

    last = fakes["adapter"].sent[-1][1]
    assert "Traceback" not in last and "db.py:42" not in last


@pytest.mark.asyncio
async def test_execute_failure_is_retriable_via_confirm(db, fakes, tmp_path):
    """Lỗi thực thi KHÔNG để request kẹt EXECUTING (ngõ cụt 'chạy lại'): quay về PLAN_REVIEW
    + nút Confirm, bấm Confirm chạy lại → thành công. Tin lỗi cũng được ghi vào nhật ký."""
    t, repo, emp, mgr = _seed(db)
    bad = ClaudeResult(ok=False, result="❌ execute lỗi", session_id="s2")
    # PLAN (analyze) → bad (execute lần 1 fail) → IMPL (execute lần 2 OK).
    claude = FakeClaude([claude_json(PLAN, "s1"), bad, claude_json(IMPL, "s3")])
    orch = _orch(db, fakes, claude)
    orch.workspace = tmp_path

    req = await orch.create_request(repo, emp, "X", "y")
    await orch.handle_callback(req, emp, cb("confirm", req.id))

    # Không kẹt EXECUTING → về PLAN_REVIEW, có nút để bấm lại.
    assert req.status == RequestStatus.PLAN_REVIEW
    fail = fakes["adapter"].sent[-1]
    assert "Confirm" in fail[1] and fail[2]          # tin lỗi kèm nút
    # Event tin lỗi được lưu (trước đây commit-trước-_say nên mất).
    from app.models import EventKind, RequestEvent
    from sqlalchemy import select
    payloads = [e.payload_json.get("payload", "") for e in db.scalars(
        select(RequestEvent).where(RequestEvent.request_id == req.id,
                                   RequestEvent.kind == EventKind.SYSTEM)).all()]
    assert any("trục trặc khi thực hiện" in p for p in payloads)

    # Bấm Confirm lại → execute chạy lại, lần này OK → VERIFY.
    await orch.handle_callback(req, emp, cb("confirm", req.id))
    assert req.status == RequestStatus.VERIFY
    assert req.pr_number == 7


@pytest.mark.asyncio
async def test_push_workflows_permission_reports_reason(db, fakes, tmp_path):
    """Push bị GitHub chặn vì app token thiếu quyền `workflows` (đụng .github/workflows/*):
    báo đúng lý do + cách xử lý, KHÔNG lặp câu 'problem saving' mù mờ."""
    t, repo, emp, mgr = _seed(db)
    claude = FakeClaude([claude_json(PLAN, "s1"), claude_json(IMPL, "s2")])
    orch = _orch(db, fakes, claude)
    orch.workspace = tmp_path

    async def _reject(*a, **k):
        raise RuntimeError(
            "git push lỗi (code 1): ! [remote rejected] bot/req-1 -> bot/req-1 "
            "(refusing to allow a GitHub App to create or update workflow "
            "`.github/workflows/ci.yml` without `workflows` permission)")
    fakes["git"].push_branch = _reject

    req = await orch.create_request(repo, emp, "X", "y")
    await orch.handle_callback(req, emp, cb("confirm", req.id))

    assert req.status == RequestStatus.PLAN_REVIEW
    last = fakes["adapter"].sent[-1][1]
    assert "Workflows" in last and "problem saving" not in last


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
async def test_merge_main_retries_once_on_405(db, fakes, tmp_path, monkeypatch):
    """GitHub trả 405 'Base branch was modified' (race) → bot thử lại 1 lần và merge xong."""
    import asyncio as _aio
    monkeypatch.setattr(_aio, "sleep", lambda *_: _noop())
    t, repo, emp, mgr = _seed(db)
    claude = FakeClaude([claude_json(PLAN, "s1"), claude_json(IMPL, "s2")])
    orch = _orch(db, fakes, claude)
    orch.workspace = tmp_path
    req = await orch.create_request(repo, emp, "X", "y")
    await orch.handle_callback(req, emp, cb("confirm", req.id))
    await orch.handle_callback(req, emp, cb("verify_ok", req.id))
    assert req.status == RequestStatus.AWAIT_MANAGER

    fakes["github"].fail_merge_405 = 1  # lần merge đầu 405, lần sau OK
    await orch.handle_callback(req, mgr, cb("mgr_approve", req.id))
    assert req.status == RequestStatus.CLOSED
    # PR release (head=dev base=main) đã merge dù lần đầu 405.
    assert any(p["base"] == "main" for p in fakes["github"].created_prs)


@pytest.mark.asyncio
async def test_merge_main_idempotent_reuses_open_pr(db, fakes, tmp_path, monkeypatch):
    """Lần duyệt đầu thất bại để lại PR release đang mở. Lần bấm sau create trả 422
    (đã có PR) → bot tra lại PR cũ và merge, thay vì kẹt vòng lặp tạo-PR-lỗi vĩnh viễn."""
    import asyncio as _aio
    monkeypatch.setattr(_aio, "sleep", lambda *_: _noop())
    t, repo, emp, mgr = _seed(db)
    claude = FakeClaude([claude_json(PLAN, "s1"), claude_json(IMPL, "s2")])
    orch = _orch(db, fakes, claude)
    orch.workspace = tmp_path
    req = await orch.create_request(repo, emp, "X", "y")
    await orch.handle_callback(req, emp, cb("confirm", req.id))
    await orch.handle_callback(req, emp, cb("verify_ok", req.id))

    # Lần 1: tạo PR release rồi merge fail (405 cả 2 lần) → kẹt AWAIT_MANAGER, PR còn mở.
    fakes["github"].fail_merge_405 = 2
    await orch.handle_callback(req, mgr, cb("mgr_approve", req.id))
    assert req.status == RequestStatus.AWAIT_MANAGER
    release_prs = [p for p in fakes["github"].created_prs if p["base"] == "main"]
    assert len(release_prs) == 1

    # Lần 2: create trả 422 (PR đã tồn tại) → tra lại PR cũ và merge xong.
    fakes["github"].fail_create_422 = 1
    await orch.handle_callback(req, mgr, cb("mgr_approve", req.id))
    assert req.status == RequestStatus.CLOSED
    assert release_prs[0]["number"] in fakes["github"].merged
    # Không tạo PR release thứ 2.
    assert len([p for p in fakes["github"].created_prs if p["base"] == "main"]) == 1


async def _noop():
    return None


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
async def test_claude_hard_error_is_retriable(db, fakes, tmp_path):
    t, repo, emp, mgr = _seed(db)
    # Claude lỗi hạ tầng (ok=False) → CLARIFYING (retriable), không kẹt ANALYZING.
    claude = FakeClaude([ClaudeResult(ok=False, result="❌ Claude lỗi (code 1)", session_id="s1")])
    orch = _orch(db, fakes, claude)
    orch.workspace = tmp_path

    req = await orch.create_request(repo, emp, "X", None)
    assert req.status == RequestStatus.CLARIFYING
    assert any("chạy lại" in s[1] for s in fakes["adapter"].sent)


@pytest.mark.asyncio
async def test_repo_prep_failure_is_friendly_and_retriable(db, fakes, tmp_path):
    """Thiếu nhánh `dev` khi clone → thông báo thân thiện (nêu rõ nhánh) + CLARIFYING; sau khi
    khách tạo nhánh, nhắn 'chạy lại' → _analyze chạy lại và ra kế hoạch."""
    from app.git_ops import GitError

    t, repo, emp, mgr = _seed(db)

    class FlakyGit(FakeGit):
        def __init__(self):
            super().__init__()
            self.calls = 0

        async def ensure_clone(self, *a, **k):
            self.calls += 1
            if self.calls == 1:  # lần đầu: chưa có nhánh dev
                raise GitError(
                    "git clone lỗi (code 128): fatal: Remote branch dev not found in upstream origin")
            return None

    fakes["git"] = FlakyGit()
    claude = FakeClaude([claude_json(PLAN, "s1")])
    orch = _orch(db, fakes, claude)
    orch.workspace = tmp_path

    req = await orch.create_request(repo, emp, "Thêm X", "chi tiết")
    assert req.status == RequestStatus.CLARIFYING
    # Thông báo thân thiện: nêu tên nhánh, KHÔNG phơi stderr thô.
    msg = next(s[1] for s in fakes["adapter"].sent if "nhánh" in s[1])
    assert repo.base_branch in msg and "chạy lại" in msg
    assert "fatal: Remote branch" not in msg

    # Khách tạo nhánh xong → "chạy lại" → clone thành công → ra kế hoạch.
    await orch.handle_message(req, emp, "chạy lại")
    assert req.status == RequestStatus.PLAN_REVIEW


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


def _mkreq(db, t, repo, emp, status, **kw):
    req = Request(tenant_id=t.id, repo_id=repo.id, requester_user_id=emp.id,
                  title="x", body="x", status=status, **kw)
    db.add(req)
    db.commit()
    return req


@pytest.mark.asyncio
async def test_verify_blocked_when_dev_slot_occupied(db, fakes, tmp_path):
    """Serialize: request khác cùng repo đang AWAIT_MANAGER ⇒ verify_ok KHÔNG merge dev,
    giữ VERIFY, gửi lại nút để bấm Đạt sau (tránh approve cuốn cả dev → mồ côi)."""
    t, repo, emp, mgr = _seed(db)
    holder = _mkreq(db, t, repo, emp, RequestStatus.AWAIT_MANAGER)
    waiter = _mkreq(db, t, repo, emp, RequestStatus.VERIFY, pr_number=9)
    orch = _orch(db, fakes, FakeClaude([]))

    await orch.handle_callback(waiter, emp, cb("verify_ok", waiter.id))

    assert waiter.status == RequestStatus.VERIFY       # chưa merge dev
    assert 9 not in fakes["github"].merged             # PR không bị merge
    last = fakes["adapter"].sent[-1]
    assert f"#{holder.id}" in last[1] and last[2]      # báo chờ + có nút verify gửi lại


@pytest.mark.asyncio
async def test_verify_proceeds_when_slot_free(db, fakes, tmp_path):
    """Holder đã CLOSED (không còn chiếm dev) ⇒ verify_ok merge dev bình thường."""
    t, repo, emp, mgr = _seed(db)
    _mkreq(db, t, repo, emp, RequestStatus.CLOSED)     # đã release, không chiếm slot
    waiter = _mkreq(db, t, repo, emp, RequestStatus.VERIFY, pr_number=9,
                    branch_name="bot/req-x")
    orch = _orch(db, fakes, FakeClaude([]))

    await orch.handle_callback(waiter, emp, cb("verify_ok", waiter.id))

    assert waiter.status == RequestStatus.AWAIT_MANAGER
    assert 9 in fakes["github"].merged


@pytest.mark.asyncio
async def test_replies_follow_requester_language_not_actor(db, fakes, tmp_path):
    """Manager (ko) thao tác trên request của requester (en): tin vào thread phải theo
    ngôn ngữ REQUESTER; riêng lỗi guard cho người bấm theo ngôn ngữ NGƯỜI BẤM."""
    t, repo, emp, mgr = _seed(db)
    emp.language = "en"
    mgr.language = "ko"
    emp2 = create_user(db, t, role=UserRole.EMPLOYEE, display_name="Eve")
    emp2.platform_user_id = "emp-2"
    emp2.language = "ko"
    db.commit()
    claude = FakeClaude([claude_json(PLAN, "s1")])
    orch = _orch(db, fakes, claude)
    orch.workspace = tmp_path
    req = await orch.create_request(repo, emp, "Fix login please right now", "detail")

    # Người khác (không phải owner, không phải manager) bấm nút → lỗi theo ngôn ngữ NGƯỜI BẤM (ko).
    await orch.handle_callback(req, emp2, cb("confirm", req.id))
    assert "요청은 당신의 것이 아닙니다" in fakes["adapter"].sent[-1][1]

    # Manager (ko) từ chối kế hoạch → tin vào thread theo ngôn ngữ requester (en).
    await orch.handle_callback(req, mgr, cb("reject", req.id))
    assert "The plan was rejected" in fakes["adapter"].sent[-1][1]


@pytest.mark.asyncio
async def test_other_approvers_notified_when_resolved(db, fakes, tmp_path):
    """Nhiều approver được DM lời mời: 1 người duyệt xong → người còn lại được báo
    (theo ngôn ngữ CỦA HỌ), người bấm không tự nhận báo."""
    t, repo, emp, mgr = _seed(db)
    admin = create_user(db, t, role=UserRole.ADMIN, display_name="Chief")
    admin.platform_user_id = "admin-9"
    admin.language = "en"
    db.commit()
    claude = FakeClaude([claude_json(PLAN, "s1"), claude_json(IMPL, "s2")])
    orch = _orch(db, fakes, claude)
    orch.workspace = tmp_path
    req = await orch.create_request(repo, emp, "X", "y")
    await orch.handle_callback(req, emp, cb("confirm", req.id))
    await orch.handle_callback(req, emp, cb("verify_ok", req.id))

    await orch.handle_callback(req, mgr, cb("mgr_approve", req.id))
    assert req.status == RequestStatus.CLOSED
    info = [s for s in fakes["adapter"].sent if s[0] == "admin-9" and "approved and deployed" in s[1]]
    assert len(info) == 1                                     # admin (en) được báo đúng ngôn ngữ
    assert not any("duyệt và triển khai" in s[1] and s[0] == "mgr-1"
                   for s in fakes["adapter"].sent)            # người bấm không tự nhận báo


@pytest.mark.asyncio
async def test_other_approvers_notified_on_reject(db, fakes, tmp_path):
    t, repo, emp, mgr = _seed(db)
    admin = create_user(db, t, role=UserRole.ADMIN, display_name="Chief")
    admin.platform_user_id = "admin-9"
    db.commit()
    claude = FakeClaude([claude_json(PLAN, "s1"), claude_json(IMPL, "s2")])
    orch = _orch(db, fakes, claude)
    orch.workspace = tmp_path
    req = await orch.create_request(repo, emp, "X", "y")
    await orch.handle_callback(req, emp, cb("confirm", req.id))
    await orch.handle_callback(req, emp, cb("verify_ok", req.id))

    await orch.handle_callback(req, mgr, cb("mgr_reject", req.id))
    assert req.status == RequestStatus.CANCELLED
    assert any(s[0] == "admin-9" and "từ chối và hoàn tác" in s[1]
               for s in fakes["adapter"].sent)


@pytest.mark.asyncio
async def test_group_origin_no_extra_approver_dm(db, fakes, tmp_path):
    """Group-origin: lời mời + kết quả đã trong group → KHÔNG DM báo thêm approver nào."""
    t, repo, emp, mgr = _seed(db)
    claude = FakeClaude([claude_json(PLAN, "s1"), claude_json(IMPL, "s2")])
    orch = _orch(db, fakes, claude)
    orch.workspace = tmp_path
    req = await orch.create_request(repo, emp, "X", "y", chat_id="group-7",
                                    platform="telegram", is_group=True)
    await orch.handle_callback(req, emp, cb("confirm", req.id))
    await orch.handle_callback(req, emp, cb("verify_ok", req.id))

    before = len([s for s in fakes["adapter"].sent if s[0] == "mgr-1"])
    await orch.handle_callback(req, mgr, cb("mgr_approve", req.id))
    assert req.status == RequestStatus.CLOSED
    assert len([s for s in fakes["adapter"].sent if s[0] == "mgr-1"]) == before
