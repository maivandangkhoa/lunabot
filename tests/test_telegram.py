"""Tests TelegramAdapter — parse_inbound (message + callback), send (inline keyboard) qua MockTransport."""
import httpx
import pytest

from app.channels.base import Button
from app.channels.telegram import TelegramAdapter


def test_parse_inbound_message():
    a = TelegramAdapter(token="t")
    raw = {"message": {"text": "fix bug", "from": {"id": 111}, "chat": {"id": 222}}}
    m = a.parse_inbound(raw)
    assert m.text == "fix bug" and m.platform_user_id == "111" and m.callback_data is None


def test_parse_inbound_callback():
    a = TelegramAdapter(token="t")
    raw = {"callback_query": {"id": "cb1", "data": "confirm:5",
                              "from": {"id": 111}, "message": {"chat": {"id": 222}}}}
    m = a.parse_inbound(raw)
    assert m.callback_data == "confirm:5" and m.platform_user_id == "111"
    assert a.callback_id(raw) == "cb1"


def test_parse_inbound_group_unaddressed():
    """Tin thường trong group (không @mention/command/reply) → is_group + KHÔNG addressed."""
    a = TelegramAdapter(token="t", bot_username="LunaBot", bot_id=42)
    raw = {"message": {"text": "anh em ăn trưa chưa", "from": {"id": 111},
                       "chat": {"id": -100, "type": "supergroup"}}}
    m = a.parse_inbound(raw)
    assert m.is_group and not m.addressed and m.chat_id == "-100"


def test_parse_inbound_group_mention_strips_and_addresses():
    a = TelegramAdapter(token="t", bot_username="LunaBot", bot_id=42)
    raw = {"message": {"text": "@LunaBot fix the bug", "from": {"id": 111},
                       "chat": {"id": -100, "type": "group"}}}
    m = a.parse_inbound(raw)
    assert m.is_group and m.addressed and m.text == "fix the bug"


def test_parse_inbound_group_command_suffix_stripped():
    a = TelegramAdapter(token="t", bot_username="LunaBot")
    raw = {"message": {"text": "/help@LunaBot", "from": {"id": 1},
                       "chat": {"id": -5, "type": "group"}}}
    m = a.parse_inbound(raw)
    assert m.addressed and m.text == "/help"


def test_parse_inbound_group_reply_to_bot_addresses():
    a = TelegramAdapter(token="t", bot_username="LunaBot", bot_id=42)
    raw = {"message": {"text": "đồng ý", "from": {"id": 1},
                       "chat": {"id": -5, "type": "group"},
                       "reply_to_message": {"from": {"id": 42}}}}
    m = a.parse_inbound(raw)
    assert m.addressed


def test_parse_inbound_private_always_addressed():
    a = TelegramAdapter(token="t", bot_username="LunaBot")
    raw = {"message": {"text": "hi", "from": {"id": 1}, "chat": {"id": 1, "type": "private"}}}
    m = a.parse_inbound(raw)
    assert not m.is_group and m.addressed


def test_parse_inbound_group_callback_addressed():
    a = TelegramAdapter(token="t", bot_username="LunaBot")
    raw = {"callback_query": {"id": "cb1", "data": "confirm:5", "from": {"id": 111},
                             "message": {"chat": {"id": -100, "type": "supergroup"}}}}
    m = a.parse_inbound(raw)
    assert m.is_group and m.addressed and m.chat_id == "-100"


@pytest.mark.asyncio
async def test_send_with_buttons_builds_inline_keyboard():
    captured = []

    def handler(req: httpx.Request) -> httpx.Response:
        import json
        captured.append((req.url.path, json.loads(req.content)))
        return httpx.Response(200, json={"ok": True, "result": {}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.telegram.org")
    a = TelegramAdapter(token="TK", client=client)
    await a.send("222", "hello", [[Button("✅ OK", "confirm:5"), Button("❌", "cancel:5")]])

    path, payload = captured[-1]
    assert path == "/botTK/sendMessage"
    assert payload["chat_id"] == "222"
    kb = payload["reply_markup"]["inline_keyboard"]
    assert kb[0][0] == {"text": "✅ OK", "callback_data": "confirm:5"}


@pytest.mark.asyncio
async def test_send_chunks_long_text():
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        return httpx.Response(200, json={"ok": True, "result": {}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.telegram.org")
    a = TelegramAdapter(token="TK", client=client)
    await a.send("1", "x" * 9000)
    assert len(calls) == 3  # 9000 / 4000 → 3 chunk
