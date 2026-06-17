"""Tests dispatcher + onboarding — /start link, tạo request từ text, route callback."""
import asyncio

import pytest

from app.dispatcher import _try_text_action, handle_channel_update, handle_telegram_update
from app.models import Request, RequestStatus, UserRole
from app.onboarding import add_repository, create_tenant, create_user, get_user_by_platform
from app.orchestrator import Orchestrator, cb
from tests.conftest import FakeClaude, RecordingGoogleChat, claude_json

PLAN = '{"action":"plan","summary":"x","steps":["a"],"risk":"low"}'


def _msg(uid, text):
    return {"message": {"text": text, "from": {"id": uid}, "chat": {"id": uid}}}


def _callback(uid, data):
    return {"callback_query": {"id": "cb1", "data": data,
                               "from": {"id": uid}, "message": {"chat": {"id": uid}}}}


def _group_msg(uid, text, chat_id):
    return {"message": {"text": text, "from": {"id": uid},
                        "chat": {"id": chat_id, "type": "supergroup"}}}


@pytest.mark.asyncio
async def test_start_links_account(db, fakes):
    t = create_tenant(db, "Acme")
    u = create_user(db, t, role=UserRole.EMPLOYEE)
    db.commit()
    await handle_telegram_update(db, fakes["adapter"], fakes["github"],
                                 _msg("99", f"/start {u.link_token}"))
    linked = get_user_by_platform(db, "telegram", "99")
    assert linked is not None and linked.id == u.id
    assert any("Đã liên kết" in s[1] for s in fakes["adapter"].sent)


@pytest.mark.asyncio
async def test_start_bad_token(db, fakes):
    await handle_telegram_update(db, fakes["adapter"], fakes["github"], _msg("99", "/start nope"))
    assert any("không hợp lệ" in s[1].lower() for s in fakes["adapter"].sent)


@pytest.mark.asyncio
async def test_unlinked_user_text_prompts_link(db, fakes):
    await handle_telegram_update(db, fakes["adapter"], fakes["github"], _msg("99", "fix bug"))
    assert any("chưa liên kết" in s[1].lower() for s in fakes["adapter"].sent)


@pytest.mark.asyncio
async def test_text_creates_request_when_single_repo(db, fakes, monkeypatch):
    import app.dispatcher as disp
    t = create_tenant(db, "Acme")
    add_repository(db, t, "acme/widgets", 123)
    u = create_user(db, t, role=UserRole.EMPLOYEE)
    u.platform_user_id = "99"
    db.commit()

    # Patch claude_run mặc định mà Orchestrator dùng (qua dispatcher tạo orch).
    fake = FakeClaude([claude_json(PLAN, "s1")])
    monkeypatch.setattr("app.orchestrator.run_claude", fake)
    # Dispatcher dùng git_ops thật → no-op hoá (phân tích cũng clone repo).
    async def _noop(*a, **k):
        return None
    monkeypatch.setattr("app.git_ops.ensure_clone", _noop)

    await handle_telegram_update(db, fakes["adapter"], fakes["github"], _msg("99", "Thêm cache"))
    reqs = u.tenant.requests
    assert len(reqs) == 1 and reqs[0].status == RequestStatus.PLAN_REVIEW


@pytest.mark.asyncio
async def test_google_chat_start_links_account(db):
    """Dispatcher channel-agnostic: /start qua Google Chat liên kết user platform=google_chat."""
    t = create_tenant(db, "Acme")
    u = create_user(db, t, role=UserRole.EMPLOYEE, platform="google_chat")
    db.commit()
    adapter = RecordingGoogleChat()
    raw = {"type": "MESSAGE", "user": {"name": "users/777"},
           "space": {"name": "spaces/AAA"},
           "message": {"text": f"/start {u.link_token}"}}
    await handle_channel_update(db, adapter, None, raw)
    linked = get_user_by_platform(db, "google_chat", "users/777")
    assert linked is not None and linked.id == u.id
    assert any("Đã liên kết" in s[1] for s in adapter.sent)


@pytest.mark.asyncio
async def test_busy_drops_second_message(db, fakes, monkeypatch):
    """Đang chạy Claude (giữ khoá) → tin thứ 2 bị báo bận + bỏ qua, KHÔNG xử lý trễ."""
    t = create_tenant(db, "Acme")
    add_repository(db, t, "acme/widgets", 123)
    u = create_user(db, t)
    u.platform_user_id = "99"
    db.commit()

    gate = asyncio.Event()
    async def blocking_claude(**kw):       # giữ task 1 lại như Claude chạy lâu
        await gate.wait()
        return claude_json(PLAN, "s1")
    monkeypatch.setattr("app.orchestrator.run_claude", blocking_claude)
    async def _noop(*a, **k):
        return None
    monkeypatch.setattr("app.git_ops.ensure_clone", _noop)

    t1 = asyncio.create_task(
        handle_telegram_update(db, fakes["adapter"], fakes["github"], _msg("99", "fix bug")))
    await asyncio.sleep(0.05)              # cho task1 vào khoá + kẹt ở Claude
    await handle_telegram_update(db, fakes["adapter"], fakes["github"], _msg("99", "tin 2"))
    assert any("đang xử lý" in s[1] for s in fakes["adapter"].sent)
    assert len(u.tenant.requests) == 1    # tin 2 không tạo request mới

    gate.set()
    await t1


@pytest.mark.asyncio
async def test_no_duplicate_request_while_open(db, fakes, monkeypatch):
    """Đang có request mở (PLAN_REVIEW) → tin mới KHÔNG tạo request trùng, báo trạng thái."""
    t = create_tenant(db, "Acme")
    add_repository(db, t, "acme/widgets", 123)
    u = create_user(db, t, role=UserRole.EMPLOYEE)
    u.platform_user_id = "99"
    db.commit()
    monkeypatch.setattr("app.orchestrator.run_claude", FakeClaude([claude_json(PLAN, "s1")]))
    async def _noop(*a, **k):
        return None
    monkeypatch.setattr("app.git_ops.ensure_clone", _noop)

    await handle_telegram_update(db, fakes["adapter"], fakes["github"], _msg("99", "Thêm cache"))
    assert len(u.tenant.requests) == 1 and u.tenant.requests[0].status == RequestStatus.PLAN_REVIEW

    # Tin thứ 2 (không phải từ khoá) → không tạo request mới, nhắc duyệt kế hoạch.
    await handle_telegram_update(db, fakes["adapter"], fakes["github"], _msg("99", "làm thêm việc khác"))
    assert len(u.tenant.requests) == 1
    assert any("chờ duyệt kế hoạch" in s[1] for s in fakes["adapter"].sent)


@pytest.mark.asyncio
async def test_clear_cancels_open_and_allows_new(db, fakes, monkeypatch):
    """/clear huỷ request đang mở → cho gửi yêu cầu mới (session mới) ngay sau đó."""
    t = create_tenant(db, "Acme")
    add_repository(db, t, "acme/widgets", 123)
    u = create_user(db, t, role=UserRole.EMPLOYEE)
    u.platform_user_id = "99"
    db.commit()
    monkeypatch.setattr("app.orchestrator.run_claude",
                        FakeClaude([claude_json(PLAN, "s1"), claude_json(PLAN, "s2")]))
    async def _noop(*a, **k):
        return None
    monkeypatch.setattr("app.git_ops.ensure_clone", _noop)

    await handle_telegram_update(db, fakes["adapter"], fakes["github"], _msg("99", "Thêm cache"))
    first = u.tenant.requests[0]
    assert first.status == RequestStatus.PLAN_REVIEW

    await handle_telegram_update(db, fakes["adapter"], fakes["github"], _msg("99", "/clear"))
    assert first.status == RequestStatus.CANCELLED
    assert any("session mới" in s[1] for s in fakes["adapter"].sent)

    # Hết blocking → tin kế tiếp tạo request mới.
    await handle_telegram_update(db, fakes["adapter"], fakes["github"], _msg("99", "Việc khác"))
    assert len(u.tenant.requests) == 2 and u.tenant.requests[1].status == RequestStatus.PLAN_REVIEW


@pytest.mark.asyncio
async def test_clear_no_open_request(db, fakes):
    """/clear khi không có request mở → báo nhẹ, không lỗi."""
    t = create_tenant(db, "Acme")
    add_repository(db, t, "acme/widgets", 123)
    u = create_user(db, t, role=UserRole.EMPLOYEE)
    u.platform_user_id = "99"
    db.commit()
    await handle_telegram_update(db, fakes["adapter"], fakes["github"], _msg("99", "/clear"))
    assert any("Không có yêu cầu đang mở" in s[1] for s in fakes["adapter"].sent)
    assert len(u.tenant.requests) == 0


@pytest.mark.asyncio
async def test_text_ok_confirms_plan(db, fakes, monkeypatch):
    """Kênh không bấm nút được (Google Chat add-on): gõ 'ok' ở PLAN_REVIEW → confirm → execute."""
    t = create_tenant(db, "Acme")
    add_repository(db, t, "acme/widgets", 123)
    u = create_user(db, t, role=UserRole.EMPLOYEE)
    u.platform_user_id = "99"
    db.commit()

    fake = FakeClaude([claude_json(PLAN, "s1"),
                       claude_json('{"action":"implemented","summary":"d","branch":"bot/req-1"}', "s2")])
    monkeypatch.setattr("app.orchestrator.run_claude", fake)
    async def _noop(*a, **k):
        return None
    async def _changed(*a, **k):
        return True
    for fn in ("ensure_clone", "prepare_branch", "push_branch"):
        monkeypatch.setattr(f"app.git_ops.{fn}", _noop)
    monkeypatch.setattr("app.git_ops.commit_all", _changed)

    await handle_telegram_update(db, fakes["adapter"], fakes["github"], _msg("99", "Thêm cache"))
    req = u.tenant.requests[0]
    assert req.status == RequestStatus.PLAN_REVIEW
    await handle_telegram_update(db, fakes["adapter"], fakes["github"], _msg("99", "ok"))
    assert req.status == RequestStatus.VERIFY


@pytest.mark.asyncio
async def test_link_rebinds_platform(db):
    """User tạo nhầm platform=telegram nhưng /start trên Google Chat → rebind google_chat."""
    t = create_tenant(db, "Acme")
    u = create_user(db, t, platform="telegram")        # admin quên --platform google_chat
    db.commit()
    adapter = RecordingGoogleChat()
    raw = {"chat": {"user": {"name": "users/777"}, "space": {"name": "spaces/A"},
                    "messagePayload": {"space": {"name": "spaces/A"},
                                       "message": {"text": f"/start {u.link_token}"}}}}
    await handle_channel_update(db, adapter, None, raw)
    linked = get_user_by_platform(db, "google_chat", "users/777")   # lookup theo kênh thực
    assert linked is not None and linked.id == u.id
    assert linked.platform == "google_chat"


@pytest.mark.asyncio
async def test_group_unaddressed_ignored(db, fakes):
    """Tin thường trong group (không @mention bot) → bỏ qua: không gửi gì, không tạo request."""
    t = create_tenant(db, "Acme")
    add_repository(db, t, "acme/widgets", 123)
    u = create_user(db, t, role=UserRole.EMPLOYEE)
    u.platform_user_id = "99"
    db.commit()
    fakes["adapter"].bot_username = "LunaBot"
    await handle_telegram_update(db, fakes["adapter"], fakes["github"],
                                 _group_msg("99", "trưa nay ăn gì", -100))
    assert fakes["adapter"].sent == []
    assert len(u.tenant.requests) == 0


@pytest.mark.asyncio
async def test_group_mention_creates_request_with_origin(db, fakes, monkeypatch):
    """@mention bot trong group → tạo request, ghi origin_chat_id=group, reply đăng trong group."""
    t = create_tenant(db, "Acme")
    add_repository(db, t, "acme/widgets", 123)
    u = create_user(db, t, role=UserRole.EMPLOYEE)
    u.platform_user_id = "99"
    db.commit()
    fakes["adapter"].bot_username = "LunaBot"
    monkeypatch.setattr("app.orchestrator.run_claude", FakeClaude([claude_json(PLAN, "s1")]))
    async def _noop(*a, **k):
        return None
    monkeypatch.setattr("app.git_ops.ensure_clone", _noop)

    await handle_telegram_update(db, fakes["adapter"], fakes["github"],
                                 _group_msg("99", "@LunaBot Thêm cache", -100))
    reqs = u.tenant.requests
    assert len(reqs) == 1 and reqs[0].status == RequestStatus.PLAN_REVIEW
    assert reqs[0].origin_chat_id == "-100" and reqs[0].origin_is_group
    assert reqs[0].title == "Thêm cache"            # @mention đã bị strip khỏi title
    assert all(s[0] == "-100" for s in fakes["adapter"].sent)   # reply vào group, không DM


@pytest.mark.asyncio
async def test_start_token_rejected_in_group(db, fakes):
    """/start <token> trong group bị từ chối (tránh lộ token) → bảo DM, không liên kết."""
    t = create_tenant(db, "Acme")
    u = create_user(db, t, role=UserRole.EMPLOYEE)
    db.commit()
    fakes["adapter"].bot_username = "LunaBot"
    await handle_telegram_update(db, fakes["adapter"], fakes["github"],
                                 _group_msg("99", f"/start {u.link_token}", -100))
    assert get_user_by_platform(db, "telegram", "99") is None
    assert any("nhắn riêng" in s[1].lower() for s in fakes["adapter"].sent)


@pytest.mark.asyncio
async def test_admin_command_blocked_in_group(db, fakes):
    """Lệnh quản trị trong group bị chặn (vd /users in token) → bảo DM."""
    t = create_tenant(db, "Acme")
    u = create_user(db, t, role=UserRole.MANAGER)
    u.platform_user_id = "99"
    db.commit()
    fakes["adapter"].bot_username = "LunaBot"
    await handle_telegram_update(db, fakes["adapter"], fakes["github"],
                                 _group_msg("99", "/users", -100))
    assert any("nhắn riêng" in s[1].lower() for s in fakes["adapter"].sent)


@pytest.mark.asyncio
async def test_callback_answered_and_routed(db, fakes, monkeypatch):
    t = create_tenant(db, "Acme")
    repo = add_repository(db, t, "acme/widgets", 123)
    u = create_user(db, t, role=UserRole.EMPLOYEE)
    u.platform_user_id = "99"
    db.commit()

    fake = FakeClaude([claude_json(PLAN, "s1"),
                       claude_json('{"action":"implemented","summary":"d","branch":"bot/req-1"}', "s2")])
    monkeypatch.setattr("app.orchestrator.run_claude", fake)
    # Dispatcher dùng git_ops thật → no-op hoá để khỏi clone thật.
    async def _noop(*a, **k):
        return None
    async def _changed(*a, **k):
        return True
    for fn in ("ensure_clone", "prepare_branch", "push_branch"):
        monkeypatch.setattr(f"app.git_ops.{fn}", _noop)
    monkeypatch.setattr("app.git_ops.commit_all", _changed)

    await handle_telegram_update(db, fakes["adapter"], fakes["github"], _msg("99", "Thêm cache"))
    req = u.tenant.requests[0]

    await handle_telegram_update(db, fakes["adapter"], fakes["github"],
                                 _callback("99", cb("confirm", req.id)))
    assert "cb1" in fakes["adapter"].answered  # đã answerCallbackQuery
    assert req.status == RequestStatus.VERIFY


# ---------------- Khử nhập nhằng lệnh "ok" (manager vừa có việc riêng vừa cần duyệt) ----------------

def _mkreq(db, t, repo, user, status):
    r = Request(tenant_id=t.id, repo_id=repo.id, requester_user_id=user.id,
                title="x", body="x", status=status)
    db.add(r)
    db.commit()
    return r


def _seed_mgr(db):
    t = create_tenant(db, "Acme")
    repo = add_repository(db, t, "acme/widgets", 123)
    emp = create_user(db, t, role=UserRole.EMPLOYEE)
    emp.platform_user_id = "emp"
    mgr = create_user(db, t, role=UserRole.MANAGER)
    mgr.platform_user_id = "mgr"
    db.commit()
    return t, repo, emp, mgr


@pytest.mark.asyncio
async def test_ok_ambiguous_asks_back(db, fakes):
    """Manager có KH của mình (PLAN_REVIEW) + 1 merge cần duyệt (AWAIT_MANAGER): 'ok' mơ hồ
    → bot hỏi lại bằng nút, KHÔNG tự đổi trạng thái cái nào."""
    t, repo, emp, mgr = _seed_mgr(db)
    own = _mkreq(db, t, repo, mgr, RequestStatus.PLAN_REVIEW)
    merge = _mkreq(db, t, repo, emp, RequestStatus.AWAIT_MANAGER)
    orch = Orchestrator(db, fakes["adapter"], github=fakes["github"])

    handled = await _try_text_action(db, orch, mgr, "ok", "mgr")

    assert handled is True
    assert own.status == RequestStatus.PLAN_REVIEW
    assert merge.status == RequestStatus.AWAIT_MANAGER
    dest, txt, buttons = fakes["adapter"].sent[-1]
    assert "nhiều việc" in txt
    flat = [b for row in buttons for b in row]
    assert {cb("confirm", own.id), cb("mgr_approve", merge.id)} == {b.callback_data for b in flat}


@pytest.mark.asyncio
async def test_ok_with_explicit_id_targets_that_request(db, fakes):
    """'ok #<merge>' duyệt đúng merge đó, KHÔNG đụng KH riêng của manager."""
    t, repo, emp, mgr = _seed_mgr(db)
    own = _mkreq(db, t, repo, mgr, RequestStatus.PLAN_REVIEW)
    merge = _mkreq(db, t, repo, emp, RequestStatus.AWAIT_MANAGER)
    orch = Orchestrator(db, fakes["adapter"], github=fakes["github"])

    handled = await _try_text_action(db, orch, mgr, f"ok #{merge.id}", "mgr")

    assert handled is True
    assert own.status == RequestStatus.PLAN_REVIEW         # KH riêng không đụng
    assert merge.status != RequestStatus.AWAIT_MANAGER     # merge đã được xử lý


@pytest.mark.asyncio
async def test_ok_with_invalid_id_reports_error(db, fakes):
    """'ok #<không hợp lệ>' → báo lỗi rõ, không đổi trạng thái."""
    t, repo, emp, mgr = _seed_mgr(db)
    own = _mkreq(db, t, repo, mgr, RequestStatus.PLAN_REVIEW)
    orch = Orchestrator(db, fakes["adapter"], github=fakes["github"])

    handled = await _try_text_action(db, orch, mgr, "ok #99999", "mgr")

    assert handled is True
    assert own.status == RequestStatus.PLAN_REVIEW
    assert any("không đang chờ" in s[1] for s in fakes["adapter"].sent)


@pytest.mark.asyncio
async def test_single_candidate_acts_directly(db, fakes):
    """Chỉ 1 việc chờ (không mơ hồ) → 'ok' duyệt luôn (giữ trải nghiệm cũ)."""
    t, repo, emp, mgr = _seed_mgr(db)
    merge = _mkreq(db, t, repo, emp, RequestStatus.AWAIT_MANAGER)
    orch = Orchestrator(db, fakes["adapter"], github=fakes["github"])

    handled = await _try_text_action(db, orch, mgr, "ok", "mgr")

    assert handled is True
    assert merge.status != RequestStatus.AWAIT_MANAGER


@pytest.mark.asyncio
async def test_message_with_hash_id_not_hijacked(db, fakes):
    """Tin thường chứa '#123' (vd 'fix bug #123') không bị coi là hành động → rơi luồng cũ."""
    t, repo, emp, mgr = _seed_mgr(db)
    _mkreq(db, t, repo, mgr, RequestStatus.PLAN_REVIEW)   # mgr có việc chờ
    orch = Orchestrator(db, fakes["adapter"], github=fakes["github"])

    handled = await _try_text_action(db, orch, mgr, "fix bug #123", "mgr")

    assert handled is False                               # không hijack
    assert fakes["adapter"].sent == []
