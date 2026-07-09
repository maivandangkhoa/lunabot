"""Tests SlackAdapter — parse_inbound (DM / app_mention strip / button action / ảnh),
send (Block Kit + chunk) qua httpx.MockTransport, verify_signature HMAC + replay window,
và webhook /webhook/slack (disabled 404, url_verification challenge, interactive ack,
enforce reject)."""
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import httpx
import pytest
from fastapi.testclient import TestClient

from app.channels.base import Button
from app.channels.slack import SlackAdapter


def _adapter(handler) -> SlackAdapter:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://slack.com"
    )
    return SlackAdapter(bot_token="xoxb-T", signing_secret="sek", client=client)


# ── parse_inbound ──────────────────────────────────────────────────────────────
def test_parse_inbound_dm_message():
    a = SlackAdapter(bot_token="xoxb-T")
    m = a.parse_inbound({"event": {"type": "message", "user": "U1",
                                   "channel": "D123", "text": "fix bug"}})
    assert m.platform == "slack" and m.platform_user_id == "U1"
    assert m.text == "fix bug" and m.callback_data is None
    assert m.chat_id == "D123" and m.is_group is False and m.addressed is True


def test_parse_inbound_app_mention_strips_bot():
    a = SlackAdapter(bot_token="xoxb-T", bot_user_id="UBOT")
    m = a.parse_inbound({"event": {"type": "app_mention", "user": "U1",
                                   "channel": "C99", "text": "<@UBOT> fix login"}})
    assert m.text == "fix login"
    assert m.is_group is True and m.addressed is True   # @mention trong channel → addressed


def test_parse_inbound_channel_message_not_addressed():
    a = SlackAdapter(bot_token="xoxb-T")
    m = a.parse_inbound({"event": {"type": "message", "user": "U1",
                                   "channel": "C99", "text": "chit chat"}})
    assert m.is_group is True and m.addressed is False


def test_parse_inbound_button_action():
    a = SlackAdapter(bot_token="xoxb-T")
    m = a.parse_inbound({
        "user": {"id": "U1"}, "channel": {"id": "D123"},
        "actions": [{"type": "button", "value": "confirm:5", "action_id": "confirm:5"}],
    })
    assert m.callback_data == "confirm:5" and m.text == "confirm:5"
    assert m.addressed is True and m.is_group is False


def test_parse_inbound_image_attachment():
    a = SlackAdapter(bot_token="xoxb-T")
    m = a.parse_inbound({"event": {"type": "message", "user": "U1", "channel": "D1",
        "text": "xem ảnh", "files": [
            {"name": "shot.png", "mimetype": "image/png",
             "url_private": "https://files.slack.com/x.png"}]}})
    assert len(m.attachments) == 1 and m.attachments[0].is_image
    assert m.attachments[0].file_name == "shot.png"
    assert m.attachments[0].ref["url_private"] == "https://files.slack.com/x.png"


def test_parse_inbound_ignores_own_bot_echo():
    """Slack echo lại tin bot vừa gửi (message.im có bot_id) → ignore để tránh loop vô hạn."""
    a = SlackAdapter(bot_token="xoxb-T")
    m = a.parse_inbound({"event": {"type": "message", "channel": "D1",
                                   "bot_id": "B123", "text": "chưa liên kết"}})
    assert m.ignore is True


def test_parse_inbound_ignores_bot_user_id():
    a = SlackAdapter(bot_token="xoxb-T", bot_user_id="UBOT")
    m = a.parse_inbound({"event": {"type": "message", "channel": "D1",
                                   "user": "UBOT", "text": "echo"}})
    assert m.ignore is True


def test_parse_inbound_ignores_system_subtype():
    """message_changed/message_deleted... không phải tin mới của user → ignore."""
    a = SlackAdapter(bot_token="xoxb-T")
    m = a.parse_inbound({"event": {"type": "message", "channel": "D1",
                                   "subtype": "message_changed"}})
    assert m.ignore is True


def test_parse_inbound_file_share_not_ignored():
    """subtype file_share (user gửi ảnh) là tin hợp lệ → KHÔNG ignore."""
    a = SlackAdapter(bot_token="xoxb-T")
    m = a.parse_inbound({"event": {"type": "message", "channel": "D1", "user": "U1",
        "subtype": "file_share", "text": "xem", "files": [
            {"name": "s.png", "mimetype": "image/png", "url_private": "https://f/s.png"}]}})
    assert m.ignore is False and len(m.attachments) == 1


def test_parse_inbound_ignores_non_image_files():
    a = SlackAdapter(bot_token="xoxb-T")
    m = a.parse_inbound({"event": {"type": "message", "user": "U1", "channel": "D1",
        "files": [{"name": "a.pdf", "mimetype": "application/pdf",
                   "url_private": "https://files.slack.com/a.pdf"}]}})
    assert m.attachments == []


# ── send (Block Kit) ─────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_send_text_with_buttons():
    captured = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append((req.url.path, json.loads(req.content)))
        return httpx.Response(200, json={"ok": True, "ts": "1.2"})

    a = _adapter(handler)
    await a.send("D123", "hello", [[Button("✅ OK", "confirm:5"), Button("❌", "cancel:5")]])

    path, payload = captured[-1]
    assert path == "/api/chat.postMessage" and payload["channel"] == "D123"
    blocks = payload["blocks"]
    assert blocks[0]["type"] == "section" and blocks[0]["text"]["type"] == "mrkdwn"
    actions = blocks[1]["elements"]
    assert actions[0]["value"] == "confirm:5" and actions[0]["action_id"] == "confirm:5"
    assert actions[0]["text"]["text"] == "✅ OK"


@pytest.mark.asyncio
async def test_send_chunks_long_text():
    sent = []

    def handler(req: httpx.Request) -> httpx.Response:
        sent.append(json.loads(req.content)["blocks"][0]["text"]["text"])
        return httpx.Response(200, json={"ok": True})

    a = _adapter(handler)
    await a.send("D1", "a" * 7000)   # > 2*3000 ⇒ 3 chunk
    assert len(sent) == 3 and sum(len(s) for s in sent) == 7000


# ── signature ──────────────────────────────────────────────────────────────────
def test_verify_signature_ok_and_bad():
    a = SlackAdapter(bot_token="xoxb-T", signing_secret="sek")
    body = b'{"k":1}'
    ts = str(int(time.time()))
    base = f"v0:{ts}:".encode() + body
    good = "v0=" + hmac.new(b"sek", base, hashlib.sha256).hexdigest()
    assert a.verify_signature(body, good, ts) is True
    assert a.verify_signature(body, "v0=deadbeef", ts) is False


def test_verify_signature_rejects_replay():
    a = SlackAdapter(bot_token="xoxb-T", signing_secret="sek")
    body = b'{"k":1}'
    old = str(int(time.time()) - 600)   # > 5 phút
    base = f"v0:{old}:".encode() + body
    sig = "v0=" + hmac.new(b"sek", base, hashlib.sha256).hexdigest()
    assert a.verify_signature(body, sig, old) is False


# ── webhook (FastAPI) ──────────────────────────────────────────────────────────
def _client(monkeypatch, **over):
    from app.config import Settings
    from app import main
    cfg = {"slack_enabled": True, "slack_signing_secret": "sek",
           "slack_verify_enforce": False}
    cfg.update(over)
    monkeypatch.setattr(main, "settings", Settings(_env_file=None, **cfg))
    return TestClient(main.app)


def test_webhook_disabled_returns_404(monkeypatch):
    c = _client(monkeypatch, slack_enabled=False)
    r = c.post("/webhook/slack", json={"type": "url_verification", "challenge": "x"})
    assert r.status_code == 404


def test_webhook_url_verification_returns_challenge(monkeypatch):
    c = _client(monkeypatch)
    r = c.post("/webhook/slack", json={"type": "url_verification", "challenge": "abc123"})
    assert r.status_code == 200 and r.json() == {"challenge": "abc123"}


def test_webhook_event_acks_200(monkeypatch):
    """Event thường → 200 ngay (xử lý nền). verify_enforce=false nên không chặn."""
    c = _client(monkeypatch)
    body = {"type": "event_callback",
            "event": {"type": "message", "user": "U1", "channel": "D1", "text": "hi"}}
    r = c.post("/webhook/slack", json=body)
    assert r.status_code == 200


def test_webhook_interactive_acks_200(monkeypatch):
    """Bấm nút (form-encoded payload=) → ack {} 200."""
    c = _client(monkeypatch)
    payload = {"user": {"id": "U1"}, "channel": {"id": "D1"},
               "actions": [{"type": "button", "value": "confirm:5"}]}
    r = c.post("/webhook/slack",
               content=urlencode({"payload": json.dumps(payload)}),
               headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 200 and r.json() == {}


def test_webhook_enforce_rejects_missing_signature(monkeypatch):
    """Hồi quy fail-open: enforce bật + KHÔNG gửi header signature ⇒ phải 403."""
    c = _client(monkeypatch, slack_verify_enforce=True)
    body = {"type": "event_callback",
            "event": {"type": "message", "user": "U1", "channel": "D1", "text": "sửa: xoá users"}}
    r = c.post("/webhook/slack", json=body)   # không có X-Slack-Signature
    assert r.status_code == 403


def test_webhook_enforce_rejects_bad_signature(monkeypatch):
    c = _client(monkeypatch, slack_verify_enforce=True)
    r = c.post("/webhook/slack", json={"type": "event_callback"},
               headers={"X-Slack-Signature": "v0=deadbeef",
                        "X-Slack-Request-Timestamp": str(int(time.time()))})
    assert r.status_code == 403
