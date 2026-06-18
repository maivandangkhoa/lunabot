"""Cô lập đa bot: cùng 1 platform_user_id ở 2 bot khác tenant không lẫn nhau."""
from __future__ import annotations

import pytest

from app.dispatcher import handle_channel_update
from app.models import Bot, UserRole
from app.onboarding import add_repository, create_tenant, create_user, get_user_by_platform
from tests.conftest import RecordingTelegram


def _msg(uid, text):
    return {"message": {"text": text, "from": {"id": uid}, "chat": {"id": uid}}}


def _setup_bot_user(db, tenant_name, repo, pid):
    t = create_tenant(db, tenant_name)
    add_repository(db, t, repo, 123)
    bot = Bot(tenant_id=t.id, platform="telegram", mode="own", username=f"{tenant_name}bot")
    db.add(bot)
    db.flush()
    u = create_user(db, t, role=UserRole.ADMIN, bot_id=bot.id)
    u.platform_user_id = pid
    db.commit()
    return t, bot, u


def test_lookup_scoped_by_bot(db):
    _, bot1, ua = _setup_bot_user(db, "Acme", "acme/x", "100")
    _, bot2, ub = _setup_bot_user(db, "Globex", "globex/y", "100")  # CÙNG pid
    assert get_user_by_platform(db, "telegram", "100", bot_id=bot1.id).id == ua.id
    assert get_user_by_platform(db, "telegram", "100", bot_id=bot2.id).id == ub.id
    assert get_user_by_platform(db, "telegram", "100", bot_id=None) is None  # bot chung khác hẳn


@pytest.mark.asyncio
async def test_message_on_other_bot_is_unlinked(db, fakes):
    """User chỉ liên kết bot1; gửi tới bot2 (cùng pid) → coi như chưa liên kết (cô lập)."""
    _, bot1, _ua = _setup_bot_user(db, "Acme", "acme/x", "100")
    _, bot2, _ub = _setup_bot_user(db, "Globex", "globex/y", "777")  # bot2 có user pid khác
    adapter = RecordingTelegram()
    # pid 100 đã link ở bot1, nhưng nhắn vào bot2 → bot2 không có user pid 100 → prompt link.
    await handle_channel_update(db, adapter, fakes["github"], _msg("100", "hello"), bot_id=bot2.id)
    assert any("chưa liên kết" in s[1].lower() for s in adapter.sent)
