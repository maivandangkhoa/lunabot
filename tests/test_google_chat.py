"""Tests GoogleChatAdapter — parse_inbound (message + card click), send (cardsV2 +
resolve space) qua httpx.MockTransport. Token inject để bỏ ký SA thật."""
import json

import httpx
import pytest

from app.channels.base import Button
from app.channels.google_chat import (
    GoogleChatAdapter,
    ack_update_message,
    is_button_click,
    load_sa_credentials,
)


def _adapter(handler) -> GoogleChatAdapter:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://chat.googleapis.com"
    )
    return GoogleChatAdapter(client=client, token_provider=lambda: "tok")


def test_parse_inbound_message():
    a = GoogleChatAdapter()
    raw = {"type": "MESSAGE", "user": {"name": "users/111"},
           "space": {"name": "spaces/AAA"},
           "message": {"text": "fix bug"}}
    m = a.parse_inbound(raw)
    assert m.platform_user_id == "users/111" and m.text == "fix bug"
    assert m.callback_data is None and m.chat_id == "spaces/AAA"


def test_parse_inbound_card_click_action_shape():
    a = GoogleChatAdapter()
    raw = {"type": "CARD_CLICKED", "user": {"name": "users/111"},
           "space": {"name": "spaces/AAA"},
           "action": {"function": "luna_action",
                      "parameters": [{"key": "cb", "value": "confirm:5"}]}}
    m = a.parse_inbound(raw)
    assert m.callback_data == "confirm:5" and m.text == "confirm:5"


def test_parse_inbound_card_click_common_shape():
    a = GoogleChatAdapter()
    raw = {"type": "CARD_CLICKED", "user": {"name": "users/111"},
           "space": {"name": "spaces/AAA"},
           "common": {"parameters": {"cb": "verify_ok:9"}}}
    m = a.parse_inbound(raw)
    assert m.callback_data == "verify_ok:9"


@pytest.mark.asyncio
async def test_send_resolves_space_and_builds_cards():
    captured = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/v1/spaces:findDirectMessage":
            return httpx.Response(200, json={"name": "spaces/DM1"})
        captured.append((req.url.path, json.loads(req.content)))
        return httpx.Response(200, json={"name": "spaces/DM1/messages/1"})

    a = _adapter(handler)
    await a.send("users/111", "hello",
                 [[Button("✅ OK", "confirm:5"), Button("❌", "cancel:5")]])

    path, payload = captured[-1]
    assert path == "/v1/spaces/DM1/messages"
    assert payload["text"] == "hello"
    btns = payload["cardsV2"][0]["card"]["sections"][0]["widgets"][0]["buttonList"]["buttons"]
    assert btns[0]["text"] == "✅ OK"
    assert btns[0]["onClick"]["action"]["parameters"] == [{"key": "cb", "value": "confirm:5"}]


@pytest.mark.asyncio
async def test_send_uses_cached_space_from_inbound():
    """parse_inbound nhớ space ⇒ send không cần gọi findDirectMessage."""
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.path)
        return httpx.Response(200, json={"name": "spaces/AAA/messages/1"})

    a = _adapter(handler)
    a.parse_inbound({"type": "MESSAGE", "user": {"name": "users/111"},
                     "space": {"name": "spaces/AAA"}, "message": {"text": "hi"}})
    await a.send("users/111", "reply")
    assert "/v1/spaces:findDirectMessage" not in calls
    assert calls == ["/v1/spaces/AAA/messages"]


@pytest.mark.asyncio
async def test_send_to_space_skips_dm_resolution():
    """destination là space sẵn (spaces/...) → gửi thẳng, KHÔNG gọi findDirectMessage."""
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.path)
        return httpx.Response(200, json={"name": "spaces/ROOM1/messages/1"})

    a = _adapter(handler)
    await a.send("spaces/ROOM1", "hi")
    assert "/v1/spaces:findDirectMessage" not in calls
    assert calls == ["/v1/spaces/ROOM1/messages"]


@pytest.mark.asyncio
async def test_group_inbound_chat_id_is_thread():
    """Group: chat_id = THREAD (1 thread = 1 request), không phải space."""
    a = GoogleChatAdapter()
    m = a.parse_inbound({"type": "MESSAGE", "user": {"name": "users/1"},
                         "space": {"name": "spaces/ROOM1", "type": "ROOM"},
                         "message": {"text": "@Luna ok", "argumentText": "ok",
                                     "thread": {"name": "spaces/ROOM1/threads/T1"}}})
    assert m.is_group and m.chat_id == "spaces/ROOM1/threads/T1"


@pytest.mark.asyncio
async def test_send_to_thread_destination_replies_in_thread():
    """destination = thread → reply đúng thread đó + set messageReplyOption; post vào space cha."""
    captured = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append((str(req.url), json.loads(req.content)))
        return httpx.Response(200, json={"name": "spaces/ROOM1/messages/1"})

    a = _adapter(handler)
    await a.send("spaces/ROOM1/threads/T1", "trả lời")
    url, payload = captured[-1]
    assert "/v1/spaces/ROOM1/messages" in url           # post vào space cha, không phải thread
    assert payload["thread"] == {"name": "spaces/ROOM1/threads/T1"}
    assert "messageReplyOption=REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD" in url


@pytest.mark.asyncio
async def test_send_dm_does_not_thread():
    """DM: destination = space (không có /threads/) → reply thẳng, không gắn thread."""
    captured = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append((str(req.url), json.loads(req.content)))
        return httpx.Response(200, json={"name": "spaces/DM1/messages/1"})

    a = _adapter(handler)
    await a.send("spaces/DM1", "trả lời")
    url, payload = captured[-1]
    assert "thread" not in payload
    assert "messageReplyOption" not in url


@pytest.mark.asyncio
async def test_send_no_thread_when_none_cached():
    """Space chưa thấy thread → gửi thường, không gắn thread/param."""
    captured = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append((str(req.url), json.loads(req.content)))
        return httpx.Response(200, json={"name": "spaces/ROOM9/messages/1"})

    a = _adapter(handler)
    await a.send("spaces/ROOM9", "hi")
    url, payload = captured[-1]
    assert "thread" not in payload
    assert "messageReplyOption" not in url


def test_parse_inbound_room_is_group():
    a = GoogleChatAdapter()
    raw = {"type": "MESSAGE", "user": {"name": "users/1"},
           "space": {"name": "spaces/ROOM1", "type": "ROOM"},
           "message": {"text": "hi"}}
    m = a.parse_inbound(raw)
    assert m.is_group and m.chat_id == "spaces/ROOM1"


def test_parse_inbound_dm_not_group():
    a = GoogleChatAdapter()
    raw = {"type": "MESSAGE", "user": {"name": "users/1"},
           "space": {"name": "spaces/DM1", "type": "DM"},
           "message": {"text": "hi"}}
    m = a.parse_inbound(raw)
    assert not m.is_group


@pytest.mark.asyncio
async def test_send_chunks_long_text():
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.path)
        return httpx.Response(200, json={"name": "n"})

    a = _adapter(handler)
    a._space_cache["users/1"] = "spaces/AAA"
    await a.send("users/1", "x" * 9000)
    assert calls.count("/v1/spaces/AAA/messages") == 3  # 9000 / 4000 → 3 chunk


@pytest.mark.asyncio
async def test_send_skips_when_no_space():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={})

    a = _adapter(handler)
    assert await a.send("users/ghost", "hi") == {}


def test_parse_inbound_message_with_image():
    a = GoogleChatAdapter()
    raw = {"chat": {"user": {"name": "users/1"}, "messagePayload": {
        "space": {"name": "spaces/A"},
        "message": {"text": "đây", "attachment": [
            {"contentName": "image.png", "contentType": "image/png",
             "attachmentDataRef": {"resourceName": "RES123"}},
            {"contentName": "doc.pdf", "contentType": "application/pdf",
             "attachmentDataRef": {"resourceName": "RESPDF"}},  # không phải ảnh → bỏ
        ]}}}}
    m = a.parse_inbound(raw)
    assert m.text == "đây" and m.platform_user_id == "users/1"
    assert len(m.attachments) == 1                         # chỉ giữ ảnh
    assert m.attachments[0].content_type == "image/png"
    assert m.attachments[0].ref["resource_name"] == "RES123"
    assert m.attachments[0].is_image


def test_parse_inbound_group_strips_bot_mention():
    """Group: text dính '@Luna'; argumentText đã strip mention → dùng để khớp 'ok'."""
    a = GoogleChatAdapter()
    raw = {"chat": {"user": {"name": "users/1"}, "messagePayload": {
        "space": {"name": "spaces/A", "type": "ROOM"},
        "message": {"text": "@Luna ok", "argumentText": " ok"}}}}
    m = a.parse_inbound(raw)
    assert m.text == "ok"          # mention bỏ + trim → khớp _W_CONFIRM


@pytest.mark.asyncio
async def test_download_attachment():
    from app.channels.base import Attachment

    captured = []
    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(req.url.path)
        return httpx.Response(200, content=b"\x89PNG-bytes")

    a = _adapter(handler)
    data = await a.download_attachment(Attachment("image.png", "image/png", {"resource_name": "RES123"}))
    assert data == b"\x89PNG-bytes"
    assert captured[-1] == "/v1/media/RES123"


@pytest.mark.asyncio
async def test_answer_callback_noop():
    assert await GoogleChatAdapter().answer_callback("x") == {}


def test_load_sa_credentials_inline_and_missing(tmp_path):
    assert load_sa_credentials(None) == {}
    assert load_sa_credentials('{"client_email": "a@b"}') == {"client_email": "a@b"}
    p = tmp_path / "sa.json"
    p.write_text('{"client_email": "file@b"}')
    assert load_sa_credentials(str(p)) == {"client_email": "file@b"}


def test_is_button_click_detects_both_shapes():
    assert is_button_click({"chat": {"buttonClickedPayload": {}}})   # add-on thật
    assert is_button_click({"type": "CARD_CLICKED"})                  # classic
    assert not is_button_click({"chat": {"messagePayload": {}}})      # tin nhắn thường
    assert not is_button_click({})


def test_ack_update_message_shape():
    # Phải là action hợp lệ; {} rỗng ⇒ Chat báo "unable to process".
    out = ack_update_message("⏳")
    assert out["hostAppDataAction"]["chatDataAction"]["updateMessageAction"][
        "message"
    ]["text"] == "⏳"


def test_webhook_button_click_returns_action(monkeypatch):
    """Webhook trả action response cho click (bỏ nút) thay vì {} rỗng."""
    from fastapi.testclient import TestClient

    import app.main as main

    async def _noop(_raw):  # cô lập khỏi DB/Claude
        return None

    monkeypatch.setattr(main, "_process_google_chat", _noop)
    monkeypatch.setattr(main.settings, "google_chat_enabled", True)
    monkeypatch.setattr(main.settings, "google_chat_audience", None)
    client = TestClient(main.app)

    click = {"chat": {"buttonClickedPayload": {"message": {}}}}
    resp = client.post("/webhook/google_chat", json=click)
    assert resp.status_code == 200
    assert "hostAppDataAction" in resp.json()

    msg = {"chat": {"messagePayload": {"message": {"text": "hi"}}}}
    resp2 = client.post("/webhook/google_chat", json=msg)
    assert resp2.status_code == 200
    assert resp2.json() == {}
