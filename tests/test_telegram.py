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
