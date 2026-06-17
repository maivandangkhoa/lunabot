"""Tests dispatcher + onboarding — /start link, tạo request từ text, route callback."""
import pytest

from app.dispatcher import handle_channel_update, handle_telegram_update
from app.models import RequestStatus, UserRole
from app.onboarding import add_repository, create_tenant, create_user, get_user_by_platform
from app.orchestrator import cb
from tests.conftest import FakeClaude, RecordingGoogleChat, claude_json

PLAN = '{"action":"plan","summary":"x","steps":["a"],"risk":"low"}'


def _msg(uid, text):
    return {"message": {"text": text, "from": {"id": uid}, "chat": {"id": uid}}}


def _callback(uid, data):
    return {"callback_query": {"id": "cb1", "data": data,
                               "from": {"id": uid}, "message": {"chat": {"id": uid}}}}


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
