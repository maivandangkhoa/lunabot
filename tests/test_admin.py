"""Tests admin CLI logic + lệnh admin qua bot + vô hiệu link_token sau khi link."""
import pytest

from app.admin_commands import handle_command
from app.dispatcher import handle_telegram_update
from app.models import Repository, User, UserRole
from app.onboarding import (
    AlreadyLinkedError,
    add_repository,
    create_tenant,
    create_user,
    get_user_by_platform,
    link_user,
)


def _admin(db, tenant):
    u = create_user(db, tenant, role=UserRole.ADMIN, display_name="Boss")
    u.platform_user_id = "admin-1"
    db.commit()
    return u


def test_link_clears_token(db):
    t = create_tenant(db, "Acme")
    u = create_user(db, t, role=UserRole.EMPLOYEE)
    tok = u.link_token
    assert tok
    linked = link_user(db, tok, "chat-9")
    assert linked.platform_user_id == "chat-9"
    assert linked.link_token is None  # token vô hiệu sau khi dùng
    # Dùng lại token cũ → không link được nữa.
    assert link_user(db, tok, "chat-x") is None


def test_shared_bot_account_links_only_one_tenant(db):
    """Bot chung (bot_id=NULL): cùng 1 tài khoản chat KHÔNG link được vào tenant thứ 2.

    Unique constraint của Postgres bỏ qua hàng có bot_id NULL ⇒ phải chặn ở tầng app.
    """
    t1 = create_tenant(db, "Acme")
    u1 = create_user(db, t1, role=UserRole.ADMIN)
    assert link_user(db, u1.link_token, "chat-7").tenant_id == t1.id

    t2 = create_tenant(db, "Globex")
    u2 = create_user(db, t2, role=UserRole.ADMIN)
    # Cùng "chat-7" định link sang tenant khác (cùng bot chung) → từ chối, không tạo trùng.
    with pytest.raises(AlreadyLinkedError):
        link_user(db, u2.link_token, "chat-7")
    # Vẫn route về tenant gốc, token tenant 2 chưa bị tiêu (link lại được sau khi đổi tài khoản).
    assert get_user_by_platform(db, "telegram", "chat-7").tenant_id == t1.id
    assert u2.link_token is not None


def test_own_bot_same_account_links_multiple_tenants(db):
    """Bot riêng: mỗi bot_id khác nhau ⇒ cùng tài khoản chat làm admin nhiều tenant (cô lập)."""
    t1 = create_tenant(db, "Acme")
    u1 = create_user(db, t1, role=UserRole.ADMIN, bot_id=11)
    t2 = create_tenant(db, "Globex")
    u2 = create_user(db, t2, role=UserRole.ADMIN, bot_id=22)
    assert link_user(db, u1.link_token, "chat-7", bot_id=11).tenant_id == t1.id
    # Cùng "chat-7" nhưng bot khác → KHÔNG bị chặn (scope theo bot_id).
    assert link_user(db, u2.link_token, "chat-7", bot_id=22).tenant_id == t2.id


@pytest.mark.asyncio
async def test_whoami_allowed_for_non_admin(db, fakes):
    t = create_tenant(db, "Acme")
    emp = create_user(db, t, role=UserRole.EMPLOYEE, display_name="Bob")
    emp.platform_user_id = "e1"
    db.commit()
    await handle_command(db, fakes["adapter"], emp, "/whoami")
    assert any("employee" in s[1] for s in fakes["adapter"].sent)


@pytest.mark.asyncio
async def test_users_requires_admin(db, fakes):
    t = create_tenant(db, "Acme")
    emp = create_user(db, t, role=UserRole.EMPLOYEE)
    emp.platform_user_id = "e1"
    db.commit()
    await handle_command(db, fakes["adapter"], emp, "/users")
    assert any("Chỉ admin" in s[1] for s in fakes["adapter"].sent)


@pytest.mark.asyncio
async def test_invite_creates_user_with_token(db, fakes):
    t = create_tenant(db, "Acme")
    admin = _admin(db, t)
    await handle_command(db, fakes["adapter"], admin, "/invite manager Nguyen Van A")
    created = db.query(User).filter(User.display_name == "Nguyen Van A").first()
    assert created is not None and created.role == UserRole.MANAGER
    assert any(created.link_token in s[1] for s in fakes["adapter"].sent)


@pytest.mark.asyncio
async def test_invite_inherits_inviter_channel(db, fakes):
    """User được mời kế thừa platform + bot_id của admin mời (không mặc định telegram)."""
    t = create_tenant(db, "Acme")
    admin = create_user(db, t, role=UserRole.ADMIN, display_name="Boss",
                        platform="google_chat", bot_id=7)
    admin.platform_user_id = "users/admin"
    db.commit()
    await handle_command(db, fakes["adapter"], admin, "/invite employee Bob")
    created = db.query(User).filter(User.display_name == "Bob").first()
    assert created is not None
    assert created.platform == "google_chat"  # không phải mặc định "telegram"
    assert created.bot_id == 7                 # cùng bot với admin mời


@pytest.mark.asyncio
async def test_role_and_unlink(db, fakes):
    t = create_tenant(db, "Acme")
    admin = _admin(db, t)
    target = create_user(db, t, role=UserRole.EMPLOYEE, display_name="X")
    target.platform_user_id = "x1"
    db.commit()

    await handle_command(db, fakes["adapter"], admin, f"/role {target.id} manager")
    assert target.role == UserRole.MANAGER

    await handle_command(db, fakes["adapter"], admin, f"/unlink {target.id}")
    assert target.platform_user_id is None and target.link_token is not None


@pytest.mark.asyncio
async def test_cross_tenant_blocked(db, fakes):
    t1 = create_tenant(db, "A")
    t2 = create_tenant(db, "B")
    admin = _admin(db, t1)
    other = create_user(db, t2, role=UserRole.EMPLOYEE, display_name="Other")
    db.commit()
    await handle_command(db, fakes["adapter"], admin, f"/role {other.id} admin")
    assert any("tìm thấy user" in s[1] for s in fakes["adapter"].sent)
    assert other.role == UserRole.EMPLOYEE  # không đổi


@pytest.mark.asyncio
async def test_addrepo_admin_only_and_creates(db, fakes):
    t = create_tenant(db, "Acme")
    admin = _admin(db, t)
    emp = create_user(db, t, role=UserRole.EMPLOYEE)
    emp.platform_user_id = "e1"
    db.commit()
    # employee bị chặn
    await handle_command(db, fakes["adapter"], emp, "/addrepo acme/widgets 123")
    assert any("Chỉ admin" in s[1] for s in fakes["adapter"].sent)
    # admin thêm được
    await handle_command(db, fakes["adapter"], admin, "/addrepo acme/widgets 123")
    r = db.query(Repository).filter(Repository.repo_full_name == "acme/widgets").first()
    assert r is not None and r.gh_installation_id == 123


@pytest.mark.asyncio
async def test_repos_and_repo_select(db, fakes):
    t = create_tenant(db, "Acme")
    r1 = add_repository(db, t, "acme/api", 1)
    r2 = add_repository(db, t, "acme/web", 2)
    emp = create_user(db, t, role=UserRole.EMPLOYEE)
    emp.platform_user_id = "e1"
    db.commit()
    await handle_command(db, fakes["adapter"], emp, "/repos")
    assert any("acme/api" in s[1] and "acme/web" in s[1] for s in fakes["adapter"].sent)
    # chọn theo tên ngắn
    await handle_command(db, fakes["adapter"], emp, "/repo web")
    assert emp.active_repo_id == r2.id
    # chọn theo số
    await handle_command(db, fakes["adapter"], emp, "/repo 1")
    assert emp.active_repo_id == r1.id


@pytest.mark.asyncio
async def test_multi_repo_requires_selection(db, fakes, monkeypatch):
    t = create_tenant(db, "Acme")
    r1 = add_repository(db, t, "acme/api", 1)
    add_repository(db, t, "acme/web", 2)
    emp = create_user(db, t, role=UserRole.EMPLOYEE)
    emp.platform_user_id = "99"
    db.commit()
    async def _noop(*a, **k):
        return None
    monkeypatch.setattr("app.git_ops.ensure_clone", _noop)

    msg = {"message": {"text": "fix bug", "from": {"id": "99"}, "chat": {"id": "99"}}}
    # Chưa chọn repo → bot bảo chọn, không tạo request.
    await handle_telegram_update(db, fakes["adapter"], fakes["github"], msg)
    assert any("/repo" in s[1] for s in fakes["adapter"].sent)
    assert t.requests == []
    # Chọn repo rồi → tạo request vào đúng repo.
    from tests.conftest import FakeClaude, claude_json
    monkeypatch.setattr("app.orchestrator.run_claude",
                        FakeClaude([claude_json('{"action":"plan","summary":"x","steps":["a"]}')]))
    emp.active_repo_id = r1.id
    db.commit()
    await handle_telegram_update(db, fakes["adapter"], fakes["github"], msg)
    assert len(t.requests) == 1 and t.requests[0].repo_id == r1.id


@pytest.mark.asyncio
async def test_dispatcher_routes_command_not_as_request(db, fakes):
    t = create_tenant(db, "Acme")
    admin = _admin(db, t)
    await handle_telegram_update(
        db, fakes["adapter"], fakes["github"],
        {"message": {"text": "/users", "from": {"id": "admin-1"}, "chat": {"id": "admin-1"}}},
    )
    # Được xử lý như lệnh (liệt kê), không tạo request.
    assert any("Users" in s[1] for s in fakes["adapter"].sent)
    assert t.requests == []


@pytest.mark.asyncio
async def test_lang_bare_shows_current_and_usage(db, fakes):
    t = create_tenant(db, "Acme")
    emp = create_user(db, t, role=UserRole.EMPLOYEE)
    emp.platform_user_id = "e1"
    emp.language = "vi"
    db.commit()
    await handle_command(db, fakes["adapter"], emp, "/lang")
    msg = fakes["adapter"].sent[-1][1]
    assert "Tiếng Việt" in msg and "/lang vi|en|ko" in msg


@pytest.mark.asyncio
async def test_lang_switch_persists_and_replies_in_new_language(db, fakes):
    t = create_tenant(db, "Acme")
    emp = create_user(db, t, role=UserRole.EMPLOYEE)
    emp.platform_user_id = "e1"
    emp.language = "vi"
    db.commit()
    await handle_command(db, fakes["adapter"], emp, "/lang ko")
    assert emp.language == "ko"                              # persist
    assert "변경했습니다" in fakes["adapter"].sent[-1][1]      # confirm bằng ngôn ngữ MỚI

    # Lệnh kế tiếp trả lời theo ngôn ngữ đã lưu (không lệ thuộc contextvar cũ).
    from app.web.i18n import set_lang
    set_lang("vi")
    await handle_command(db, fakes["adapter"], emp, "/lang")
    assert "현재 언어" in fakes["adapter"].sent[-1][1]


@pytest.mark.asyncio
async def test_lang_invalid_shows_usage(db, fakes):
    t = create_tenant(db, "Acme")
    emp = create_user(db, t, role=UserRole.EMPLOYEE)
    emp.platform_user_id = "e1"
    db.commit()
    await handle_command(db, fakes["adapter"], emp, "/lang xx")
    assert "/lang vi|en|ko" in fakes["adapter"].sent[-1][1]
    assert emp.language is None
