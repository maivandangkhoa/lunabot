"""Tests dispatcher + onboarding — /start link, tạo request từ text, route callback."""
import asyncio

import pytest

from app.claude_runner import ClaudeResult
from app.dispatcher import (
    _intent_enabled, _try_text_action, handle_channel_update, handle_telegram_update,
)
from app.intent import Intent
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
async def test_dm_does_not_hijack_open_group_request(db, fakes, monkeypatch):
    """User có request đang mở TRONG GROUP; nhắn DM phải tạo request DM MỚI (reply về DM),
    không cuốn vào request-group → tránh bot trả lời DM sang group."""
    t = create_tenant(db, "Acme")
    add_repository(db, t, "acme/widgets", 123)
    u = create_user(db, t, role=UserRole.EMPLOYEE)
    u.platform_user_id = "99"
    # Request đang mở, khởi tạo từ group -100.
    db.add(Request(
        tenant_id=t.id, repo_id=t.repositories[0].id, requester_user_id=u.id,
        title="cũ", status=RequestStatus.PLAN_REVIEW,
        origin_chat_id="-100", origin_is_group=True,
    ))
    db.commit()
    monkeypatch.setattr("app.orchestrator.run_claude", FakeClaude([claude_json(PLAN, "s1")]))
    async def _noop(*a, **k):
        return None
    monkeypatch.setattr("app.git_ops.ensure_clone", _noop)

    # DM: chat.id == from.id == "99" (Telegram DM).
    await handle_telegram_update(db, fakes["adapter"], fakes["github"], _msg("99", "Thêm cache"))
    reqs = u.tenant.requests
    assert len(reqs) == 2                                   # request DM mới, không đụng request-group
    new = max(reqs, key=lambda r: r.id)
    assert new.origin_chat_id == "99" and not new.origin_is_group
    assert all(s[0] == "99" for s in fakes["adapter"].sent)   # mọi phản hồi ở DM, không lọt group


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
async def test_safe_command_allowed_in_group(db, fakes):
    """Lệnh chỉ-đọc (/whoami) chạy được trong group và trả lời ngay trong thread."""
    t = create_tenant(db, "Acme")
    u = create_user(db, t, role=UserRole.EMPLOYEE)
    u.platform_user_id = "99"
    db.commit()
    fakes["adapter"].bot_username = "LunaBot"
    await handle_telegram_update(db, fakes["adapter"], fakes["github"],
                                 _group_msg("99", "@LunaBot /whoami", -100))
    # Không bị chặn DM-only, và reply về group (-100) chứ không DM riêng.
    assert not any("nhắn riêng" in s[1].lower() for s in fakes["adapter"].sent)
    assert any(s[0] == "-100" for s in fakes["adapter"].sent)
    assert any(str(u.id) in s[1] for s in fakes["adapter"].sent)


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


@pytest.mark.asyncio
async def test_callback_cross_tenant_gets_feedback(db, fakes):
    """Bot dùng chung: người ở tenant KHÁC bấm nút của 1 request → không route (status giữ
    nguyên) NHƯNG được báo rõ thay vì bỏ qua im lặng (bug làm request trông như treo)."""
    ta = create_tenant(db, "Acme")
    repo = add_repository(db, ta, "acme/widgets", 123)
    owner = create_user(db, ta, role=UserRole.EMPLOYEE)
    req = Request(tenant_id=ta.id, repo_id=repo.id, requester_user_id=owner.id,
                  title="x", body="x", status=RequestStatus.VERIFY)
    db.add(req)
    tb = create_tenant(db, "Other")
    outsider = create_user(db, tb, role=UserRole.EMPLOYEE)
    outsider.platform_user_id = "88"
    db.commit()

    await handle_telegram_update(db, fakes["adapter"], fakes["github"],
                                 _callback("88", cb("verify_ok", req.id)))
    assert req.status == RequestStatus.VERIFY                       # KHÔNG bị route
    assert any("thao tác được" in s[1] for s in fakes["adapter"].sent)  # có báo, không im lặng


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
async def test_verify_button_label_echo_advances_not_loops(db, fakes):
    """VERIFY: user echo NGUYÊN nhãn nút '✅ Đạt' (kênh không route click, vd Messenger) → khớp
    verify_ok → merge dev (rời VERIFY), KHÔNG bị coi là feedback chạy lại EXECUTING vô tận."""
    t, repo, emp, mgr = _seed_mgr(db)
    req = _mkreq(db, t, repo, emp, RequestStatus.VERIFY)
    req.pr_number = 7
    db.commit()
    orch = Orchestrator(db, fakes["adapter"], github=fakes["github"])

    handled = await _try_text_action(db, orch, emp, "✅ Đạt", "emp")

    assert handled is True
    assert req.status != RequestStatus.VERIFY              # đã tiến tới (merge dev → chờ manager)


@pytest.mark.asyncio
async def test_disambig_button_label_echo_routes_by_id(db, fakes):
    """Echo NGUYÊN nhãn nút khử-nhập-nhằng '✅ Allow merge #53' (Messenger gửi click dạng text)
    → khớp mgr_approve đúng #53, KHÔNG rơi thành feedback chạy lại request đang mở khác."""
    t, repo, emp, mgr = _seed_mgr(db)
    merge = _mkreq(db, t, repo, emp, RequestStatus.AWAIT_MANAGER)
    merge.pr_number = 3
    other = _mkreq(db, t, repo, mgr, RequestStatus.VERIFY)   # việc đang mở khác của manager
    db.commit()
    orch = Orchestrator(db, fakes["adapter"], github=fakes["github"])

    handled = await _try_text_action(db, orch, mgr, f"✅ Allow merge #{merge.id}", "mgr")

    assert handled is True
    assert merge.status != RequestStatus.AWAIT_MANAGER      # đã duyệt merge production
    assert other.status == RequestStatus.VERIFY             # KHÔNG đụng việc khác


@pytest.mark.asyncio
async def test_disambig_label_vietnamese_echo(db, fakes):
    """Nhãn tiếng Việt '✅ Cho merge #id' echo dạng text cũng route đúng mgr_approve."""
    t, repo, emp, mgr = _seed_mgr(db)
    merge = _mkreq(db, t, repo, emp, RequestStatus.AWAIT_MANAGER)
    merge.pr_number = 4
    db.commit()
    orch = Orchestrator(db, fakes["adapter"], github=fakes["github"])

    handled = await _try_text_action(db, orch, mgr, f"✅ Cho merge #{merge.id}", "mgr")

    assert handled is True
    assert merge.status != RequestStatus.AWAIT_MANAGER


@pytest.mark.asyncio
async def test_keyword_symbol_strip_keeps_phrase_guard(db, fakes):
    """Strip emoji KHÔNG được nới lỏng thành khớp token: 'fix bug' vẫn không phải hành động."""
    t, repo, emp, mgr = _seed_mgr(db)
    _mkreq(db, t, repo, emp, RequestStatus.VERIFY)
    orch = Orchestrator(db, fakes["adapter"], github=fakes["github"])

    handled = await _try_text_action(db, orch, emp, "fix bug đăng nhập", "emp")

    assert handled is False                                # rơi về luồng feedback cũ, không khớp nút


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
async def test_ask_answers_without_creating_request(db, fakes, monkeypatch):
    """/ask trả lời chỉ-đọc, KHÔNG tạo request; prompt gửi Claude là nguyên câu hỏi."""
    t = create_tenant(db, "Acme")
    add_repository(db, t, "acme/widgets", 123)
    u = create_user(db, t, role=UserRole.EMPLOYEE)
    u.platform_user_id = "99"
    db.commit()
    fake = FakeClaude([ClaudeResult(ok=True, result="Dự án dùng Postgres.", session_id=None)])
    monkeypatch.setattr("app.orchestrator.run_claude", fake)
    async def _noop(*a, **k):
        return None
    monkeypatch.setattr("app.git_ops.ensure_clone", _noop)

    await handle_telegram_update(db, fakes["adapter"], fakes["github"],
                                 _msg("99", "/ask dự án này dùng DB gì?"))
    assert len(u.tenant.requests) == 0                       # KHÔNG qua FSM
    assert any("Postgres" in s[1] for s in fakes["adapter"].sent)
    assert fake.calls[0]["prompt"] == "dự án này dùng DB gì?"
    assert fake.calls[0]["permission_mode"].value == "default"   # chỉ-đọc


@pytest.mark.asyncio
async def test_ask_without_question_shows_usage(db, fakes):
    """/ask không kèm câu hỏi → nhắc cú pháp, không gọi Claude, không tạo request."""
    t = create_tenant(db, "Acme")
    add_repository(db, t, "acme/widgets", 123)
    u = create_user(db, t, role=UserRole.EMPLOYEE)
    u.platform_user_id = "99"
    db.commit()
    await handle_telegram_update(db, fakes["adapter"], fakes["github"], _msg("99", "/ask"))
    assert any("Hướng dẫn sử dụng: /ask" in s[1] for s in fakes["adapter"].sent)
    assert len(u.tenant.requests) == 0


@pytest.mark.asyncio
async def test_ask_allowed_in_group_replies_publicly(db, fakes, monkeypatch):
    """/ask dùng được trong group (không bị chặn DM-only) → trả lời công khai trong group."""
    t = create_tenant(db, "Acme")
    add_repository(db, t, "acme/widgets", 123)
    u = create_user(db, t, role=UserRole.EMPLOYEE)
    u.platform_user_id = "99"
    db.commit()
    fakes["adapter"].bot_username = "LunaBot"
    monkeypatch.setattr("app.orchestrator.run_claude",
                        FakeClaude([ClaudeResult(ok=True, result="Câu trả lời.", session_id=None)]))
    async def _noop(*a, **k):
        return None
    monkeypatch.setattr("app.git_ops.ensure_clone", _noop)

    await handle_telegram_update(db, fakes["adapter"], fakes["github"],
                                 _group_msg("99", "@LunaBot /ask repo dùng gì?", -100))
    assert any("Câu trả lời." in s[1] for s in fakes["adapter"].sent)
    assert all(s[0] == "-100" for s in fakes["adapter"].sent)    # reply trong group, không DM
    assert len(u.tenant.requests) == 0


@pytest.mark.asyncio
async def test_message_with_hash_id_not_hijacked(db, fakes):
    """Tin thường chứa '#123' (vd 'fix bug #123') không bị coi là hành động → rơi luồng cũ."""
    t, repo, emp, mgr = _seed_mgr(db)
    _mkreq(db, t, repo, mgr, RequestStatus.PLAN_REVIEW)   # mgr có việc chờ
    orch = Orchestrator(db, fakes["adapter"], github=fakes["github"])

    handled = await _try_text_action(db, orch, mgr, "fix bug #123", "mgr")

    assert handled is False                               # không hijack
    assert fakes["adapter"].sent == []


# ---------------- Manager làm rõ/feedback thay nhân viên trong cùng thread (1 thread 1 request) ----

def _thread_req(db, t, repo, owner, status, chat_id="-100", **kw):
    r = Request(tenant_id=t.id, repo_id=repo.id, requester_user_id=owner.id, title="x", body="x",
                status=status, origin_chat_id=chat_id, origin_is_group=True,
                origin_platform="telegram", **kw)
    db.add(r)
    db.commit()
    return r


@pytest.mark.asyncio
async def test_manager_clarifies_employee_request_in_thread(db, fakes, monkeypatch):
    """Request của nhân viên đang CLARIFYING trong group → MANAGER trả lời làm rõ thay → tiến tiếp."""
    t, repo, emp, mgr = _seed_mgr(db)
    req = _thread_req(db, t, repo, emp, RequestStatus.CLARIFYING)
    fakes["adapter"].bot_username = "LunaBot"
    monkeypatch.setattr("app.orchestrator.run_claude", FakeClaude([claude_json(PLAN, "s2")]))
    async def _noop(*a, **k):
        return None
    monkeypatch.setattr("app.git_ops.ensure_clone", _noop)

    await handle_telegram_update(db, fakes["adapter"], fakes["github"],
                                 _group_msg("mgr", "@LunaBot Dùng Postgres", -100))

    assert req.status == RequestStatus.PLAN_REVIEW       # làm rõ của manager đã đẩy request đi tiếp
    assert len(t.requests) == 1                          # không tạo request mới


@pytest.mark.asyncio
async def test_manager_feedback_verify_in_thread(db, fakes, monkeypatch):
    """Request của nhân viên đang VERIFY → MANAGER gõ mô tả sửa thay → vào luồng fix với đúng feedback."""
    t, repo, emp, mgr = _seed_mgr(db)
    req = _thread_req(db, t, repo, emp, RequestStatus.VERIFY, pr_number=7, branch_name="bot/req-1")
    fakes["adapter"].bot_username = "LunaBot"
    fake = FakeClaude([claude_json('{"action":"implemented","summary":"d","branch":"bot/req-1"}', "s2")])
    monkeypatch.setattr("app.orchestrator.run_claude", fake)
    async def _noop(*a, **k):
        return None
    async def _changed(*a, **k):
        return True
    for fn in ("ensure_clone", "prepare_branch", "push_branch"):
        monkeypatch.setattr(f"app.git_ops.{fn}", _noop)
    monkeypatch.setattr("app.git_ops.commit_all", _changed)

    await handle_telegram_update(db, fakes["adapter"], fakes["github"],
                                 _group_msg("mgr", "@LunaBot thêm validation input", -100))

    assert any("thêm validation input" in c["prompt"] for c in fake.calls)  # feedback manager → fix
    assert req.status == RequestStatus.VERIFY            # fix xong quay lại VERIFY


@pytest.mark.asyncio
async def test_other_member_cannot_chen_thread_request(db, fakes):
    """Thành viên khác (không phải chủ/không manager) gõ trong thread đang có request → nhắc thread mới."""
    t, repo, emp, mgr = _seed_mgr(db)
    other = create_user(db, t, role=UserRole.EMPLOYEE)
    other.platform_user_id = "other"
    db.commit()
    req = _thread_req(db, t, repo, emp, RequestStatus.CLARIFYING)
    fakes["adapter"].bot_username = "LunaBot"

    await handle_telegram_update(db, fakes["adapter"], fakes["github"],
                                 _group_msg("other", "@LunaBot Cho tôi việc khác", -100))

    assert any("thread mới" in s[1].lower() for s in fakes["adapter"].sent)
    assert len(t.requests) == 1                          # KHÔNG tạo request mới trong cùng thread


# ---------------- Lớp 2: LLM hiểu câu tự nhiên khi từ khoá trượt (xác nhận trước, không execute) ----

def _patch_classify(monkeypatch, intent):
    monkeypatch.setattr("app.dispatcher._intent_enabled", lambda: True)
    async def _classify(text, statuses, **k):
        return intent
    monkeypatch.setattr("app.dispatcher.classify_intent", _classify)


@pytest.mark.asyncio
async def test_llm_low_confidence_asks_confirm_not_execute(db, fakes, monkeypatch):
    """Câu tự nhiên, LLM chưa đủ chắc (conf<ngưỡng) → bot XIN XÁC NHẬN (nút), KHÔNG tự duyệt."""
    t, repo, emp, mgr = _seed_mgr(db)
    req = _mkreq(db, t, repo, emp, RequestStatus.PLAN_REVIEW)
    orch = Orchestrator(db, fakes["adapter"], github=fakes["github"])
    _patch_classify(monkeypatch, Intent("ok", 0.5))      # dưới 0.75

    handled = await _try_text_action(db, orch, emp, "chắc là ổn rồi nhỉ", "emp")

    assert handled is True
    assert req.status == RequestStatus.PLAN_REVIEW       # CHƯA execute — chờ xác nhận
    dest, txt, buttons = fakes["adapter"].sent[-1]
    assert "xác nhận" in txt.lower()
    flat = [b for row in buttons for b in row]
    assert cb("confirm", req.id) in {b.callback_data for b in flat}


@pytest.mark.asyncio
async def test_llm_high_confidence_executes_directly(db, fakes, monkeypatch):
    """LLM đủ chắc + việc hoàn-tác-được (confirm trên dev) → làm THẲNG, không bắt xác nhận lại."""
    t, repo, emp, mgr = _seed_mgr(db)
    req = _mkreq(db, t, repo, emp, RequestStatus.PLAN_REVIEW)
    orch = Orchestrator(db, fakes["adapter"], github=fakes["github"])
    _patch_classify(monkeypatch, Intent("ok", 0.95))     # trên 0.75
    calls = []
    async def _hc(r, u, data, **k):
        calls.append((r.id, data))
    monkeypatch.setattr(orch, "handle_callback", _hc)

    handled = await _try_text_action(db, orch, emp, "ừ làm luôn đi em", "emp")

    assert handled is True
    assert calls == [(req.id, cb("confirm", req.id))]    # execute thẳng
    assert fakes["adapter"].sent == []                   # KHÔNG hỏi xác nhận


@pytest.mark.asyncio
async def test_llm_irreversible_always_confirms(db, fakes, monkeypatch):
    """Merge production (mgr_approve) KHÔNG hoàn tác → LUÔN xác nhận dù LLM rất chắc (sàn an toàn)."""
    t, repo, emp, mgr = _seed_mgr(db)
    merge = _mkreq(db, t, repo, emp, RequestStatus.AWAIT_MANAGER)
    orch = Orchestrator(db, fakes["adapter"], github=fakes["github"])
    _patch_classify(monkeypatch, Intent("ok", 0.99))     # rất chắc

    handled = await _try_text_action(db, orch, mgr, "cho lên production luôn", "mgr")

    assert handled is True
    assert merge.status == RequestStatus.AWAIT_MANAGER   # CHƯA merge — sàn an toàn bắt xác nhận
    dest, txt, buttons = fakes["adapter"].sent[-1]
    flat = [b for row in buttons for b in row]
    assert cb("mgr_approve", merge.id) in {b.callback_data for b in flat}


@pytest.mark.asyncio
async def test_llm_fallback_none_falls_through(db, fakes, monkeypatch):
    """LLM trả None (không phải hành động cổng) → _try_text_action False → rơi luồng cũ (feedback)."""
    t, repo, emp, mgr = _seed_mgr(db)
    _mkreq(db, t, repo, emp, RequestStatus.PLAN_REVIEW)
    orch = Orchestrator(db, fakes["adapter"], github=fakes["github"])
    monkeypatch.setattr("app.dispatcher._intent_enabled", lambda: True)
    called = {"n": 0}
    async def _classify(text, statuses, **k):
        called["n"] += 1
        return None
    monkeypatch.setattr("app.dispatcher.classify_intent", _classify)

    handled = await _try_text_action(db, orch, emp, "nút đăng nhập vẫn còn lệch trên mobile", "emp")
    assert called["n"] == 1                               # đã thực sự gọi LLM (PLAN_REVIEW là cổng thuần)

    assert handled is False
    assert fakes["adapter"].sent == []


@pytest.mark.asyncio
async def test_llm_fallback_not_triggered_at_verify(db, fakes, monkeypatch):
    """VERIFY: văn bản tự do là PHẢN HỒI (nội dung) → KHÔNG gọi LLM, để rơi vào luồng feedback cũ."""
    t, repo, emp, mgr = _seed_mgr(db)
    _mkreq(db, t, repo, emp, RequestStatus.VERIFY)
    orch = Orchestrator(db, fakes["adapter"], github=fakes["github"])
    monkeypatch.setattr("app.dispatcher._intent_enabled", lambda: True)
    async def _boom(*a, **k):
        raise AssertionError("KHÔNG được gọi LLM ở VERIFY (đó là feedback, không phải cổng quyết định)")
    monkeypatch.setattr("app.dispatcher.classify_intent", _boom)

    handled = await _try_text_action(db, orch, emp, "vẫn còn lỗi chỗ đăng nhập nhé", "emp")

    assert handled is False                               # rơi luồng cũ → handle_message (feedback)


@pytest.mark.asyncio
async def test_llm_fallback_disabled_skips_classify(db, fakes, monkeypatch):
    """Tắt Lớp 2 → KHÔNG gọi LLM, giữ hành vi chỉ-từ-khoá (câu lạ → False → luồng cũ)."""
    t, repo, emp, mgr = _seed_mgr(db)
    _mkreq(db, t, repo, emp, RequestStatus.PLAN_REVIEW)
    orch = Orchestrator(db, fakes["adapter"], github=fakes["github"])
    monkeypatch.setattr("app.dispatcher._intent_enabled", lambda: False)
    async def _boom(*a, **k):
        raise AssertionError("không được gọi LLM khi Lớp 2 tắt")
    monkeypatch.setattr("app.dispatcher.classify_intent", _boom)

    handled = await _try_text_action(db, orch, emp, "được rồi triển khai đi", "emp")

    assert handled is False                               # rơi luồng cũ (plan_pending)
    assert fakes["adapter"].sent == []


def test_intent_enabled_requires_token(monkeypatch):
    """Guard: bật cờ nhưng thiếu OAuth token ⇒ vẫn tắt (không bao giờ gọi LLM khi chưa cấu hình)."""
    from app.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "intent_llm_enabled", True)
    monkeypatch.setattr(s, "claude_code_oauth_token", None)
    assert _intent_enabled() is False
    monkeypatch.setattr(s, "claude_code_oauth_token", "tok")
    assert _intent_enabled() is True
    monkeypatch.setattr(s, "intent_llm_enabled", False)
    assert _intent_enabled() is False


def test_keyword_gop_maps_conflict_fix_only_in_await_manager():
    """"gộp" → conflict_fix chỉ ở AWAIT_MANAGER (guard `offered` trong branch_sync mới
    quyết có chạy thật); các trạng thái khác không map thành hành động này."""
    from app.dispatcher import _keyword_action

    assert _keyword_action("gộp", RequestStatus.AWAIT_MANAGER) == "conflict_fix"
    assert _keyword_action("gộp", RequestStatus.PLAN_REVIEW) is None
    assert _keyword_action("gộp", RequestStatus.VERIFY) is None


@pytest.mark.asyncio
async def test_lang_command_allowed_in_group(db, fakes):
    t = create_tenant(db, "Acme")
    u = create_user(db, t, role=UserRole.EMPLOYEE)
    u.platform_user_id = "99"
    u.language = "vi"
    db.commit()
    fakes["adapter"].bot_username = "LunaBot"
    await handle_telegram_update(db, fakes["adapter"], fakes["github"],
                                 _group_msg("99", "@LunaBot /lang en", -100))
    assert u.language == "en"
    assert not any("nhắn riêng" in s[1].lower() for s in fakes["adapter"].sent)
    assert any(s[0] == "-100" and "Language switched" in s[1] for s in fakes["adapter"].sent)


@pytest.mark.asyncio
async def test_start_does_not_persist_language(db, fakes):
    """Ngôn ngữ chốt từ TIN ĐẦU user gửi, không phải locale client lúc /start —
    nếu /start ghi sẵn cột thì detection không bao giờ chạy."""
    t = create_tenant(db, "Acme")
    u = create_user(db, t, role=UserRole.EMPLOYEE)
    db.commit()
    raw = _msg("99", f"/start {u.link_token}")
    raw["message"]["from"]["language_code"] = "en"
    await handle_telegram_update(db, fakes["adapter"], fakes["github"], raw)
    assert get_user_by_platform(db, "telegram", "99").language is None
