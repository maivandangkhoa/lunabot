"""Tests branch_sync — phân kỳ prod↔base lúc nhận request (confirm trước khi gộp) +
gỡ xung đột merge release lên prod (manager confirm rồi bot resolve).

Bất biến: KHÔNG BAO GIỜ tự merge prod vào base khi chưa có xác nhận tường minh.
"""
import pytest

from app.claude_runner import ClaudeResult
from app.models import ApprovalDecision, RequestStatus, UserRole
from app.onboarding import add_repository, create_tenant, create_user
from app.orchestrator import Orchestrator, cb
from tests.conftest import FakeClaude, claude_json

PLAN = '{"action":"plan","summary":"do x","steps":["a","b"],"risk":"low"}'
IMPL = '{"action":"implemented","summary":"done","branch":"bot/req-1"}'
RESOLVED = ClaudeResult(ok=True, result="đã gỡ xong conflict", session_id="s-cf")


def _seed(db):
    t = create_tenant(db, "Acme")
    repo = add_repository(db, t, "acme/widgets", 12345)
    repo.settings_json = {"deploy_gate": False}
    emp = create_user(db, t, role=UserRole.EMPLOYEE, display_name="Bob")
    emp.platform_user_id = "emp-1"
    mgr = create_user(db, t, role=UserRole.MANAGER, display_name="Alice")
    mgr.platform_user_id = "mgr-1"
    db.commit()
    return t, repo, emp, mgr


def _orch(db, fakes, claude, tmp_path):
    o = Orchestrator(db, fakes["adapter"], github=fakes["github"],
                     claude_run=claude, git=fakes["git"])
    o.workspace = tmp_path
    return o


def _btn_actions(sent_entry):
    return [b.callback_data.split(":")[0] for row in (sent_entry[2] or []) for b in row]


async def _to_await_manager(db, fakes, tmp_path, extra_claude=()):
    """Đưa 1 request tới AWAIT_MANAGER (không phân kỳ lúc intake)."""
    t, repo, emp, mgr = _seed(db)
    claude = FakeClaude([claude_json(PLAN, "s1"), claude_json(IMPL, "s2"), *extra_claude])
    orch = _orch(db, fakes, claude, tmp_path)
    req = await orch.create_request(repo, emp, "X", "y")
    await orch.handle_callback(req, emp, cb("confirm", req.id))
    await orch.handle_callback(req, emp, cb("verify_ok", req.id))
    assert req.status == RequestStatus.AWAIT_MANAGER
    return orch, req, emp, mgr, claude


# ---------------- Feature 1: phân kỳ lúc nhận request ----------------

@pytest.mark.asyncio
async def test_intake_no_divergence_flows_normally(db, fakes, tmp_path):
    t, repo, emp, mgr = _seed(db)
    orch = _orch(db, fakes, FakeClaude([claude_json(PLAN, "s1")]), tmp_path)
    req = await orch.create_request(repo, emp, "X", "y")
    assert req.status == RequestStatus.PLAN_REVIEW
    assert not any("bản chạy thật" in s[1] for s in fakes["adapter"].sent)


@pytest.mark.asyncio
async def test_intake_divergence_asks_confirmation_before_any_merge(db, fakes, tmp_path):
    t, repo, emp, mgr = _seed(db)
    fakes["git"].divergence_count = 2
    claude = FakeClaude([claude_json(PLAN, "s1")])
    orch = _orch(db, fakes, claude, tmp_path)

    req = await orch.create_request(repo, emp, "X", "y")
    assert req.status == RequestStatus.CLARIFYING
    assert req.report_json["prod_sync"]["state"] == "asked"
    ask = fakes["adapter"].sent[-1]
    assert "bản chạy thật" in ask[1] and "`main`" in ask[1]
    assert _btn_actions(ask) == ["sync_yes", "sync_no"]
    # CHƯA phân tích, CHƯA merge/push gì khi chưa xác nhận.
    assert claude.calls == [] and fakes["git"].pushed == []


@pytest.mark.asyncio
async def test_sync_yes_clean_merge_then_continues(db, fakes, tmp_path):
    t, repo, emp, mgr = _seed(db)
    fakes["git"].divergence_count = 1
    orch = _orch(db, fakes, FakeClaude([claude_json(PLAN, "s1")]), tmp_path)
    req = await orch.create_request(repo, emp, "X", "y")

    await orch.handle_callback(req, emp, cb("sync_yes", req.id))
    assert req.report_json["prod_sync"]["state"] == "confirmed"
    assert fakes["git"].pushed == ["dev"]                    # đã gộp & push base
    assert any("Đã cập nhật" in s[1] for s in fakes["adapter"].sent)
    assert req.status == RequestStatus.PLAN_REVIEW           # phân tích chạy tiếp


@pytest.mark.asyncio
async def test_sync_yes_conflict_resolved_by_claude(db, fakes, tmp_path):
    t, repo, emp, mgr = _seed(db)
    fakes["git"].divergence_count = 1
    fakes["git"].merge_conflict = True
    claude = FakeClaude([RESOLVED, claude_json(PLAN, "s1")])
    orch = _orch(db, fakes, claude, tmp_path)
    req = await orch.create_request(repo, emp, "X", "y")

    await orch.handle_callback(req, emp, cb("sync_yes", req.id))
    assert req.report_json["prod_sync"]["state"] == "confirmed"
    # Claude được gọi resolve với bypass + resume session, prompt nêu file conflict.
    resolve_call = claude.calls[0]
    assert resolve_call["permission_mode"].value == "bypassPermissions"
    assert "src/Navbar.tsx" in resolve_call["prompt"]
    assert fakes["git"].pushed == ["dev"]
    assert req.status == RequestStatus.PLAN_REVIEW


@pytest.mark.asyncio
async def test_sync_declined_by_button_never_reasks(db, fakes, tmp_path):
    t, repo, emp, mgr = _seed(db)
    fakes["git"].divergence_count = 1
    orch = _orch(db, fakes, FakeClaude(
        [claude_json(PLAN, "s1"), claude_json(PLAN, "s2")]), tmp_path)
    req = await orch.create_request(repo, emp, "X", "y")

    await orch.handle_callback(req, emp, cb("sync_no", req.id))
    assert req.report_json["prod_sync"]["state"] == "declined"
    assert fakes["git"].pushed == []                          # không merge gì
    assert any("tiếp tục trên bản hiện tại" in s[1] for s in fakes["adapter"].sent)
    assert req.status == RequestStatus.PLAN_REVIEW

    # Người dùng chỉnh kế hoạch → re-analyze; vẫn phân kỳ nhưng KHÔNG hỏi lại.
    await orch.handle_callback(req, emp, cb("reject", req.id))
    await orch.handle_message(req, emp, "đổi màu nút thành xanh")
    assert req.status == RequestStatus.PLAN_REVIEW
    asks = [s for s in fakes["adapter"].sent if "bản chạy thật" in s[1]]
    assert len(asks) == 1                                     # chỉ câu hỏi ban đầu


@pytest.mark.asyncio
async def test_sync_text_yes_and_text_no(db, fakes, tmp_path):
    t, repo, emp, mgr = _seed(db)
    fakes["git"].divergence_count = 1
    orch = _orch(db, fakes, FakeClaude([claude_json(PLAN, "s1")]), tmp_path)
    req = await orch.create_request(repo, emp, "X", "y")

    await orch.handle_message(req, emp, "ok")                 # text thay nút
    assert req.report_json["prod_sync"]["state"] == "confirmed"
    assert fakes["git"].pushed == ["dev"]
    assert req.status == RequestStatus.PLAN_REVIEW


@pytest.mark.asyncio
async def test_sync_free_text_declines_and_becomes_clarification(db, fakes, tmp_path):
    t, repo, emp, mgr = _seed(db)
    fakes["git"].divergence_count = 1
    claude = FakeClaude([claude_json(PLAN, "s1")])
    orch = _orch(db, fakes, claude, tmp_path)
    req = await orch.create_request(repo, emp, "X", "y")

    await orch.handle_message(req, emp, "thêm cả nút xoá nhé")
    assert req.report_json["prod_sync"]["state"] == "declined"
    assert fakes["git"].pushed == []
    # Text tự do được chuyển tiếp làm câu trả lời làm rõ cho phân tích.
    assert "thêm cả nút xoá nhé" in claude.calls[0]["prompt"]
    assert req.status == RequestStatus.PLAN_REVIEW


@pytest.mark.asyncio
async def test_sync_failure_notifies_and_continues(db, fakes, tmp_path):
    t, repo, emp, mgr = _seed(db)
    fakes["git"].divergence_count = 1

    async def boom(*a, **k):
        raise RuntimeError("push rejected")
    fakes["git"].push_branch = boom
    orch = _orch(db, fakes, FakeClaude([claude_json(PLAN, "s1")]), tmp_path)
    req = await orch.create_request(repo, emp, "X", "y")

    await orch.handle_callback(req, emp, cb("sync_yes", req.id))
    assert req.report_json["prod_sync"]["state"] == "failed"
    assert any("chưa gộp tự động được" in s[1].lower() for s in fakes["adapter"].sent)
    assert req.status == RequestStatus.PLAN_REVIEW            # không kẹt


# ---------------- Feature 2: conflict khi merge release ----------------

@pytest.mark.asyncio
async def test_merge_main_conflict_405_offers_fix_instead_of_generic_error(db, fakes, tmp_path):
    orch, req, emp, mgr, _ = await _to_await_manager(db, fakes, tmp_path)

    fakes["github"].fail_merge_405_conflict = 1
    await orch.handle_callback(req, mgr, cb("mgr_approve", req.id))

    assert req.status == RequestStatus.AWAIT_MANAGER          # vẫn duyệt lại/từ chối được
    assert req.report_json["conflict_fix"]["offered"] is True
    ask = fakes["adapter"].sent[-1]
    assert "sửa trực tiếp" in ask[1]
    assert _btn_actions(ask) == ["conflict_fix", "mgr_reject"]
    # KHÔNG gửi lỗi chung "thử duyệt lại" gây hiểu lầm.
    assert not any("duyệt lại" in s[1].lower() for s in fakes["adapter"].sent)


@pytest.mark.asyncio
async def test_conflict_fix_resolves_merges_and_closes(db, fakes, tmp_path):
    orch, req, emp, mgr, claude = await _to_await_manager(
        db, fakes, tmp_path, extra_claude=(RESOLVED,))
    fakes["github"].fail_merge_405_conflict = 1
    await orch.handle_callback(req, mgr, cb("mgr_approve", req.id))

    fakes["git"].merge_conflict = True
    await orch.handle_callback(req, mgr, cb("conflict_fix", req.id))

    assert fakes["git"].pushed[-1] == "dev"                   # prod đã gộp vào base
    assert req.status == RequestStatus.CLOSED                 # merge main trọn đường cũ
    assert any(a.decision == ApprovalDecision.APPROVED for a in req.approvals)
    assert req.branch_name in fakes["github"].deleted_branches


@pytest.mark.asyncio
async def test_conflict_fix_requires_manager(db, fakes, tmp_path):
    orch, req, emp, mgr, _ = await _to_await_manager(db, fakes, tmp_path)
    fakes["github"].fail_merge_405_conflict = 1
    await orch.handle_callback(req, mgr, cb("mgr_approve", req.id))

    await orch.handle_callback(req, emp, cb("conflict_fix", req.id))
    assert req.status == RequestStatus.AWAIT_MANAGER
    assert "dev" not in fakes["git"].pushed                   # không sync gì
    assert "manager" in fakes["adapter"].sent[-1][1].lower()


@pytest.mark.asyncio
async def test_conflict_fix_double_click_guarded(db, fakes, tmp_path):
    orch, req, emp, mgr, _ = await _to_await_manager(db, fakes, tmp_path)
    fakes["github"].fail_merge_405_conflict = 1
    await orch.handle_callback(req, mgr, cb("mgr_approve", req.id))

    req.report_json = {**req.report_json, "conflict_fix": {"offered": True, "running": True}}
    db.commit()
    await orch.handle_callback(req, mgr, cb("conflict_fix", req.id))
    assert any("đang xử lý" in s[1].lower() for s in fakes["adapter"].sent)
    assert "dev" not in fakes["git"].pushed


@pytest.mark.asyncio
async def test_conflict_fix_claude_fails_aborts_and_stays_retryable(db, fakes, tmp_path):
    orch, req, emp, mgr, claude = await _to_await_manager(
        db, fakes, tmp_path, extra_claude=(RESOLVED,))
    fakes["github"].fail_merge_405_conflict = 1
    await orch.handle_callback(req, mgr, cb("mgr_approve", req.id))

    fakes["git"].merge_conflict = True
    fakes["git"].markers_after_resolve = True                 # Claude "resolve" nhưng còn marker
    await orch.handle_callback(req, mgr, cb("conflict_fix", req.id))

    assert fakes["git"].merge_aborted >= 1                    # worktree được dọn sạch
    assert req.status == RequestStatus.AWAIT_MANAGER
    assert req.report_json["conflict_fix"]["running"] is False  # bấm thử lại được
    fail = fakes["adapter"].sent[-1]
    assert "chưa tự gộp được" in fail[1].lower()
    assert _btn_actions(fail) == ["conflict_fix", "mgr_reject"]


@pytest.mark.asyncio
async def test_conflict_fix_without_offer_is_rejected(db, fakes, tmp_path):
    """Keyword/nút lạc khi CHƯA hề có conflict → không tự ý sync."""
    orch, req, emp, mgr, _ = await _to_await_manager(db, fakes, tmp_path)

    await orch.handle_callback(req, mgr, cb("conflict_fix", req.id))
    assert "dev" not in fakes["git"].pushed
    assert any("xử lý" in s[1] or "#" in s[1] for s in fakes["adapter"].sent)
    assert req.status == RequestStatus.AWAIT_MANAGER


@pytest.mark.asyncio
async def test_race_405_still_retries_not_offers_fix(db, fakes, tmp_path, monkeypatch):
    """405 'Base branch was modified' (race) giữ nguyên retry cũ, KHÔNG mời gộp conflict."""
    import asyncio as _aio

    async def _noop(*_):
        return None
    monkeypatch.setattr(_aio, "sleep", _noop)
    orch, req, emp, mgr, _ = await _to_await_manager(db, fakes, tmp_path)

    fakes["github"].fail_merge_405 = 1
    await orch.handle_callback(req, mgr, cb("mgr_approve", req.id))
    assert req.status == RequestStatus.CLOSED
    assert "conflict_fix" not in (req.report_json or {})


@pytest.mark.asyncio
async def test_sync_button_label_echo_with_emoji_confirms(db, fakes, tmp_path):
    """Messenger/Zalo echo nhãn nút thành TEXT '✅ Gộp vào' (kèm emoji) — phải hiểu là
    ĐỒNG Ý, không được đọc nhầm thành từ chối (bug thực tế 2026-07-04)."""
    t, repo, emp, mgr = _seed(db)
    fakes["git"].divergence_count = 1
    orch = _orch(db, fakes, FakeClaude([claude_json(PLAN, "s1")]), tmp_path)
    req = await orch.create_request(repo, emp, "X", "y")

    await orch.handle_message(req, emp, "✅ Gộp vào")
    assert req.report_json["prod_sync"]["state"] == "confirmed"
    assert fakes["git"].pushed == ["dev"]
    assert req.status == RequestStatus.PLAN_REVIEW


@pytest.mark.asyncio
async def test_sync_button_label_echo_no_declines(db, fakes, tmp_path):
    t, repo, emp, mgr = _seed(db)
    fakes["git"].divergence_count = 1
    orch = _orch(db, fakes, FakeClaude([claude_json(PLAN, "s1")]), tmp_path)
    req = await orch.create_request(repo, emp, "X", "y")

    await orch.handle_message(req, emp, "⏭️ Cứ làm tiếp")
    assert req.report_json["prod_sync"]["state"] == "declined"
    assert fakes["git"].pushed == []
    assert req.status == RequestStatus.PLAN_REVIEW           # vẫn phân tích tiếp


@pytest.mark.asyncio
async def test_conflict_flow_dm_uses_approver_language(db, fakes, tmp_path):
    """DM: lời mời gỡ conflict + tin trạng thái theo ngôn ngữ APPROVER (không phải requester)."""
    orch, req, emp, mgr, claude = await _to_await_manager(
        db, fakes, tmp_path, extra_claude=(RESOLVED,))
    emp.language = "vi"
    mgr.language = "en"
    db.commit()

    fakes["github"].fail_merge_405_conflict = 1
    await orch.handle_callback(req, mgr, cb("mgr_approve", req.id))
    ask = fakes["adapter"].sent[-1]
    assert "Couldn't deploy request" in ask[1]                # tiếng Anh (approver, DM)

    fakes["git"].merge_conflict = True
    await orch.handle_callback(req, mgr, cb("conflict_fix", req.id))
    assert any("Combining the two changes" in s[1] for s in fakes["adapter"].sent)
    # Tin đóng request cuối vào thread requester → tiếng Việt.
    assert any(f"Yêu cầu #{req.id} đã merge" in s[1] for s in fakes["adapter"].sent)
