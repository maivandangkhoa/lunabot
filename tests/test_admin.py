"""Tests admin CLI logic + lệnh admin qua bot + vô hiệu link_token sau khi link."""
import pytest

from app.admin_commands import handle_command
from app.dispatcher import handle_telegram_update
from app.models import User, UserRole
from app.onboarding import (
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
    assert any("Không tìm thấy" in s[1] for s in fakes["adapter"].sent)
    assert other.role == UserRole.EMPLOYEE  # không đổi


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
