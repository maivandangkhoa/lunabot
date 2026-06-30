"""Tests MessengerAdapter — parse_inbound (text / quick_reply / postback / ảnh), send
(chunk + quick_replies) qua httpx.MockTransport, verify_signature HMAC, và webhook
verify GET (challenge) + POST (tách entry[].messaging[])."""
import hashlib
import hmac
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.channels.base import Button
from app.channels.messenger import MessengerAdapter, merge_events


def _adapter(handler) -> MessengerAdapter:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://graph.facebook.com/v21.0"
    )
    return MessengerAdapter(page_access_token="PAT", app_secret="sek", client=client)


# ── parse_inbound ──────────────────────────────────────────────────────────────
def test_parse_inbound_text():
    a = MessengerAdapter(page_access_token="PAT")
    m = a.parse_inbound({"sender": {"id": "PSID1"}, "recipient": {"id": "PAGE"},
                         "message": {"text": "fix bug"}})
    assert m.platform == "messenger" and m.platform_user_id == "PSID1"
    assert m.text == "fix bug" and m.callback_data is None
    assert m.chat_id == "PSID1" and m.is_group is False


def test_parse_inbound_quick_reply():
    a = MessengerAdapter(page_access_token="PAT")
    m = a.parse_inbound({"sender": {"id": "PSID1"},
                         "message": {"text": "OK", "quick_reply": {"payload": "confirm:5"}}})
    assert m.callback_data == "confirm:5" and m.text == "confirm:5"


def test_parse_inbound_postback():
    a = MessengerAdapter(page_access_token="PAT")
    m = a.parse_inbound({"sender": {"id": "PSID1"},
                         "postback": {"title": "Approve", "payload": "verify_ok:9"}})
    assert m.callback_data == "verify_ok:9" and m.text == "Approve"


def test_parse_inbound_image_attachment():
    a = MessengerAdapter(page_access_token="PAT")
    m = a.parse_inbound({"sender": {"id": "PSID1"}, "message": {
        "attachments": [{"type": "image", "payload": {"url": "https://cdn/x.jpg"}}]}})
    assert len(m.attachments) == 1 and m.attachments[0].is_image
    assert m.attachments[0].ref["url"] == "https://cdn/x.jpg"


# ── merge_events (gộp ảnh + chữ trong 1 POST) ────────────────────────────────────
def test_merge_events_combines_image_and_text_same_sender():
    """Ảnh + chữ user gửi một lượt (Messenger tách event, chung 1 POST) → 1 event có cả hai."""
    out = merge_events([
        {"sender": {"id": "PSID1"}, "message": {"attachments": [
            {"type": "image", "payload": {"url": "https://cdn/x.jpg"}}]}},
        {"sender": {"id": "PSID1"}, "message": {"text": "fix this screen"}},
    ])
    assert len(out) == 1
    msg = out[0]["message"]
    assert msg["text"] == "fix this screen"
    assert msg["attachments"][0]["payload"]["url"] == "https://cdn/x.jpg"


def test_merge_events_keeps_different_senders_separate():
    out = merge_events([
        {"sender": {"id": "A"}, "message": {"text": "hi"}},
        {"sender": {"id": "B"}, "message": {"text": "yo"}},
    ])
    assert len(out) == 2


def test_merge_events_does_not_merge_quick_reply():
    """Bấm nút (quick_reply) là hành động riêng → KHÔNG gộp vào tin thường cùng sender."""
    out = merge_events([
        {"sender": {"id": "A"}, "message": {"text": "hi"}},
        {"sender": {"id": "A"}, "message": {"text": "OK", "quick_reply": {"payload": "confirm:5"}}},
    ])
    assert len(out) == 2


def test_merge_events_does_not_mutate_input():
    src = [
        {"sender": {"id": "A"}, "message": {"attachments": [{"type": "image"}]}},
        {"sender": {"id": "A"}, "message": {"text": "caption"}},
    ]
    merge_events(src)
    assert "text" not in src[0]["message"]          # event gốc không bị thêm text
    assert len(src[0]["message"]["attachments"]) == 1


# ── send ───────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_send_text_with_quick_replies():
    captured = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append((req.url.path, dict(req.url.params), json.loads(req.content)))
        return httpx.Response(200, json={"message_id": "mid.1"})

    a = _adapter(handler)
    await a.send("PSID1", "hello", [[Button("✅ OK", "confirm:5"), Button("❌", "cancel:5")]])

    path, params, payload = captured[-1]
    assert path == "/v21.0/me/messages" and params["access_token"] == "PAT"
    assert payload["recipient"]["id"] == "PSID1"
    assert payload["message"]["text"] == "hello"
    qr = payload["message"]["quick_replies"]
    assert qr[0] == {"content_type": "text", "title": "✅ OK", "payload": "confirm:5"}


@pytest.mark.asyncio
async def test_send_chunks_long_text():
    sent = []

    def handler(req: httpx.Request) -> httpx.Response:
        sent.append(json.loads(req.content)["message"]["text"])
        return httpx.Response(200, json={"message_id": "x"})

    a = _adapter(handler)
    await a.send("PSID1", "a" * 4500)   # > 2*2000 ⇒ 3 chunk
    assert len(sent) == 3 and sum(len(s) for s in sent) == 4500


# ── signature ──────────────────────────────────────────────────────────────────
def test_verify_signature_ok_and_bad():
    a = MessengerAdapter(page_access_token="PAT", app_secret="sek")
    body = b'{"k":1}'
    good = "sha256=" + hmac.new(b"sek", body, hashlib.sha256).hexdigest()
    assert a.verify_signature(body, good) is True
    assert a.verify_signature(body, "sha256=deadbeef") is False


# ── webhook (FastAPI) ──────────────────────────────────────────────────────────
def _client(monkeypatch, **over):
    from app.config import Settings
    from app import main
    cfg = {"messenger_enabled": True, "messenger_verify_token": "VT",
           "messenger_app_secret": "sek", "messenger_verify_enforce": False}
    cfg.update(over)
    monkeypatch.setattr(main, "settings", Settings(_env_file=None, **cfg))
    return TestClient(main.app)


def test_webhook_verify_returns_challenge(monkeypatch):
    c = _client(monkeypatch)
    r = c.get("/webhook/messenger", params={
        "hub.mode": "subscribe", "hub.verify_token": "VT", "hub.challenge": "12345"})
    assert r.status_code == 200 and r.text == "12345"


def test_webhook_verify_rejects_bad_token(monkeypatch):
    c = _client(monkeypatch)
    r = c.get("/webhook/messenger", params={
        "hub.mode": "subscribe", "hub.verify_token": "WRONG", "hub.challenge": "x"})
    assert r.status_code == 403


def test_webhook_disabled_returns_404(monkeypatch):
    c = _client(monkeypatch, messenger_enabled=False)
    r = c.get("/webhook/messenger", params={"hub.mode": "subscribe",
                                            "hub.verify_token": "VT", "hub.challenge": "x"})
    assert r.status_code == 404


def test_webhook_post_acks_200(monkeypatch):
    """POST hợp lệ → 200 ngay (xử lý nền). verify_enforce=false nên không chặn dù chưa ký."""
    c = _client(monkeypatch)
    body = {"object": "page", "entry": [{"messaging": [
        {"sender": {"id": "PSID1"}, "message": {"text": "hi"}}]}]}
    r = c.post("/webhook/messenger", json=body)
    assert r.status_code == 200
