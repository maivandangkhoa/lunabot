"""MessengerAdapter — hiện thực ChannelAdapter qua Facebook Messenger Platform (Graph API).

Điểm khác Telegram/Zalo:
- Auth bằng **Page Access Token** (long-lived, không cần refresh như Zalo) → đơn giản hơn.
- Không có inline keyboard 2D → render thành **Quick Replies** (giống Zalo). User bấm →
  webhook gửi message.quick_reply.payload; postback button → postback.payload → callback_data.
- answer_callback: no-op (Messenger không có spinner).
- DM 1:1 là chính (Page không có group chat như Telegram) → is_group luôn False.
- Webhook verify: GET hub.challenge/hub.verify_token khi đăng ký; POST ký bằng
  HMAC-SHA256(app_secret, body) ở header X-Hub-Signature-256.

`parse_inbound` nhận MỘT 'messaging' event (đã tách từ entry[].messaging[] ở webhook),
không phải toàn bộ body — vì 1 POST của Messenger có thể gộp nhiều event.

Refs: https://developers.facebook.com/docs/messenger-platform
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.channels.base import Attachment, Button, InboundMessage

log = logging.getLogger("luna.messenger")

_GRAPH_API = "https://graph.facebook.com/v21.0"
_MAX_LEN = 2000  # Messenger giới hạn text 2000 ký tự


@dataclass
class MessengerAdapter:
    """Adapter Facebook Messenger — shared OA (env) hoặc own page (BYO token)."""

    page_access_token: str
    app_secret: str = ""
    page_id: str | None = None       # để lọc đúng page nếu cần
    api_base: str = _GRAPH_API
    client: httpx.AsyncClient | None = None
    name: str = "messenger"

    _group_ids: set[str] = field(default_factory=set, init=False, repr=False)

    @classmethod
    def from_settings(cls, settings=None) -> "MessengerAdapter":
        from app.config import get_settings
        s = settings or get_settings()
        return cls(
            page_access_token=s.messenger_page_access_token or "",
            app_secret=s.messenger_app_secret or "",
            page_id=s.messenger_page_id,
        )

    def _http(self) -> httpx.AsyncClient:
        if self.client is None:
            self.client = httpx.AsyncClient(base_url=self.api_base, timeout=30)
        return self.client

    async def aclose(self) -> None:
        if self.client is not None:
            await self.client.aclose()
            self.client = None

    # ----- Inbound -----

    def verify_signature(self, body: bytes, signature: str) -> bool:
        """Verify HMAC-SHA256(app_secret, body). signature dạng 'sha256=<hex>'."""
        sig = signature.removeprefix("sha256=")
        expected = hmac.new(self.app_secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sig)

    def parse_inbound(self, raw: dict) -> InboundMessage:
        """Một 'messaging' event của Messenger → InboundMessage.

        Hỗ trợ: message text (+ quick_reply payload), postback button, attachment ảnh.
        """
        sender = raw.get("sender", {})
        uid = str(sender.get("id", ""))
        msg = raw.get("message", {}) or {}
        postback = raw.get("postback", {}) or {}

        text = msg.get("text", "") or ""
        callback_data: str | None = None

        qr = msg.get("quick_reply")
        if isinstance(qr, dict) and qr.get("payload"):
            callback_data = str(qr["payload"])
            text = callback_data
        elif postback.get("payload"):
            callback_data = str(postback["payload"])
            text = postback.get("title") or callback_data

        attachments: list[Attachment] = []
        for att in msg.get("attachments") or []:
            if att.get("type") == "image":
                url = (att.get("payload") or {}).get("url", "")
                if url:
                    attachments.append(Attachment("image.jpg", "image/jpeg", {"url": url}))

        return InboundMessage(
            platform=self.name,
            platform_user_id=uid,
            text=text,
            callback_data=callback_data,
            chat_id=uid,
            is_group=False,          # Page Messenger là DM 1:1
            addressed=True,
            attachments=attachments,
            raw=raw,
        )

    # ----- Outbound -----

    def _quick_replies(self, buttons: list[list[Button]] | None) -> list[dict] | None:
        """Button grid → Quick Reply list (Messenger không có inline keyboard 2D)."""
        if not buttons:
            return None
        return [
            {"content_type": "text", "title": b.text, "payload": b.callback_data}
            for row in buttons for b in row
        ]

    async def send(
        self,
        destination: str,
        text: str,
        buttons: list[list[Button]] | None = None,
    ) -> Any:
        """Gửi tin tới user (PSID). Chunk nếu dài; quick replies gắn chunk cuối."""
        params = {"access_token": self.page_access_token}
        chunks = [text[i: i + _MAX_LEN] for i in range(0, len(text), _MAX_LEN)] or [""]
        result: Any = {}

        for idx, chunk in enumerate(chunks):
            message: dict[str, Any] = {"text": chunk}
            if idx == len(chunks) - 1:
                qr = self._quick_replies(buttons)
                if qr:
                    message["quick_replies"] = qr
            payload = {
                "recipient": {"id": destination},
                "messaging_type": "RESPONSE",
                "message": message,
            }
            resp = await self._http().post("/me/messages", params=params, json=payload)
            data = resp.json()
            if data.get("error"):
                log.warning("messenger sendMessage lỗi: %s", data)
            else:
                result = data
        return result

    async def answer_callback(self, callback_id: str, text: str | None = None) -> dict:
        """Messenger không có spinner — no-op cho hợp protocol ChannelAdapter."""
        return {}

    async def download_attachment(self, attachment: Attachment) -> bytes:
        """Tải ảnh từ URL CDN Messenger (URL công khai có chữ ký, không cần auth)."""
        url = attachment.ref.get("url", "")
        if not url:
            raise ValueError("Attachment không có URL.")
        resp = await self._http().get(url)
        if resp.status_code != 200:
            raise RuntimeError(f"download_attachment lỗi {resp.status_code}")
        return resp.content
