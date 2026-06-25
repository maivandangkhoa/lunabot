"""ZaloAdapter — hiện thực ChannelAdapter qua Zalo OA Open API v3.

Điểm khác biệt so với Telegram:
- Access token TTL ~1h → tự refresh qua refresh_token (giống GoogleChatAdapter).
- Không có inline callback button → render thành Quick Reply (text button). Khi user
  click, Zalo gửi event user_send_text với message.quick_reply.payload → callback_data.
- answer_callback: no-op (Zalo không có spinner).
- Group chat: OA nhận event dạng g.usr.send.* khi OA được thêm vào group.
  Group ID được cache trong _group_ids để send() chọn đúng endpoint.
- Webhook verify: GET challenge-response khi đăng ký; POST dùng HMAC-SHA256(app_secret, body).

Refs: https://developers.zalo.me/docs/api/official-account-api
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.channels.base import Attachment, Button, InboundMessage
from app.channels.formatting import format_for, split_chunks

log = logging.getLogger("luna.zalo")

_OA_API = "https://openapi.zalo.me"
_TOKEN_URL = "https://oauth.zaloapp.com/v4/oa/access_token"
_MAX_LEN = 2000  # Zalo giới hạn text ~2000 ký tự

_GROUP_EVENTS = frozenset({
    "g.usr.send.text", "g.usr.send.img", "g.usr.send.gif",
    "g.usr.send.sticker", "g.usr.send.audio", "g.usr.send.video",
    "g.usr.send.file", "g.usr.send.link",
})


@dataclass
class ZaloAdapter:
    """Adapter Zalo OA Open API v3 — dùng được cho cả shared OA (env) và own OA (BYO)."""

    app_id: str
    app_secret: str
    access_token: str              # token ban đầu (từ env hoặc DB)
    refresh_token: str | None = None
    oa_id: str | None = None       # OA ID (để lọc event đúng OA nếu nhiều OA cùng app)
    api_base: str = _OA_API
    client: httpx.AsyncClient | None = None
    name: str = "zalo"

    # Cache nội bộ (không dùng làm init arg)
    _token: str = field(default="", init=False, repr=False)
    _token_exp: float = field(default=0.0, init=False, repr=False)
    _group_ids: set[str] = field(default_factory=set, init=False, repr=False)

    def __post_init__(self) -> None:
        self._token = self.access_token

    @classmethod
    def from_settings(cls, settings=None) -> "ZaloAdapter":
        from app.config import get_settings
        s = settings or get_settings()
        return cls(
            app_id=s.zalo_app_id or "",
            app_secret=s.zalo_app_secret or "",
            access_token=s.zalo_oa_access_token or "",
            refresh_token=s.zalo_oa_refresh_token,
            oa_id=s.zalo_oa_id,
        )

    def _http(self) -> httpx.AsyncClient:
        if self.client is None:
            self.client = httpx.AsyncClient(base_url=self.api_base, timeout=30)
        return self.client

    async def aclose(self) -> None:
        if self.client is not None:
            await self.client.aclose()
            self.client = None

    # ----- Auth -----

    async def _get_token(self) -> str:
        """Trả access token; refresh nếu còn < 60s hoặc chưa có exp."""
        now = time.time()
        if self._token and self._token_exp and now < self._token_exp - 60:
            return self._token
        if not self.refresh_token:
            return self._token
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                resp = await c.post(
                    _TOKEN_URL,
                    data={
                        "app_id": self.app_id,
                        "grant_type": "refresh_token",
                        "refresh_token": self.refresh_token,
                        "app_secret": self.app_secret,
                    },
                )
            data = resp.json()
            new_token = data.get("access_token")
            if new_token:
                self._token = new_token
                self._token_exp = now + int(data.get("expires_in", 3600))
                if data.get("refresh_token"):
                    self.refresh_token = data["refresh_token"]
            else:
                log.warning("zalo: không lấy được access_token mới: %s", data)
        except Exception:  # noqa: BLE001
            log.exception("zalo refresh token lỗi")
        return self._token

    # ----- Inbound -----

    def verify_signature(self, body: bytes, signature: str) -> bool:
        """Verify HMAC-SHA256(app_secret, body). signature dạng 'sha256=<hex>' hoặc '<hex>'."""
        sig = signature.removeprefix("sha256=")
        expected = hmac.new(self.app_secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sig)

    def parse_inbound(self, raw: dict) -> InboundMessage:
        """Event Zalo OA (webhook POST body) → InboundMessage.

        Hỗ trợ: user_send_text (có quick_reply payload), user_send_image, group events.
        """
        event = raw.get("event_name", "")
        is_group = event in _GROUP_EVENTS
        sender = raw.get("sender", {})
        recipient = raw.get("recipient", {})
        msg = raw.get("message", {})

        uid = str(sender.get("id", ""))
        # DM: chat_id = user id; group: chat_id = group id (trong recipient.id)
        chat_id = str(recipient.get("id", uid)) if is_group else uid

        if is_group and chat_id:
            self._group_ids.add(chat_id)   # nhớ để send() chọn endpoint group

        text = msg.get("text", "") or ""
        callback_data: str | None = None

        # Quick reply click: payload gắn trong message.quick_reply.payload
        qr = msg.get("quick_reply")
        if isinstance(qr, dict) and qr.get("payload"):
            callback_data = str(qr["payload"])
            text = callback_data

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
            chat_id=chat_id,
            is_group=is_group,
            addressed=True,   # Zalo OA chỉ nhận tin nhắm tới OA
            attachments=attachments,
            raw=raw,
        )

    # ----- Outbound -----

    def _quick_replies(self, buttons: list[list[Button]] | None) -> list[dict] | None:
        """Button grid → Quick Reply list (Zalo không có inline keyboard 2D)."""
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
        """Gửi tin tới user (DM) hoặc group (chunk nếu dài). Quick replies gắn chunk cuối.

        `destination` là user_id hoặc group_id. ZaloAdapter tự phát hiện loại dựa trên
        cache _group_ids được nạp lúc parse_inbound. Orchestrator truyền origin_chat_id
        nên routing đúng miễn parse_inbound đã được gọi cho request đó.
        """
        token = await self._get_token()
        headers = {"access_token": token}
        is_group_dest = destination in self._group_ids
        body, _ = format_for(self.name, text)  # Zalo không có rich text → strip markdown về plain
        chunks = split_chunks(body, _MAX_LEN)
        result: Any = {}

        for idx, chunk in enumerate(chunks):
            msg_body: dict[str, Any] = {"text": chunk}
            if idx == len(chunks) - 1:
                qr = self._quick_replies(buttons)
                if qr:
                    msg_body["quick_replies"] = qr

            if is_group_dest:
                payload = {"recipient": {"group_id": destination}, "message": msg_body}
                endpoint = "/v3.0/oa/message/g.cs"
            else:
                payload = {"recipient": {"user_id": destination}, "message": msg_body}
                endpoint = "/v3.0/oa/message/cs"

            resp = await self._http().post(endpoint, json=payload, headers=headers)
            data = resp.json()
            if data.get("error") not in (None, 0):
                log.warning("zalo sendMessage lỗi: %s", data)
            else:
                result = data
        return result

    async def answer_callback(self, callback_id: str, text: str | None = None) -> dict:
        """Zalo không có spinner — no-op cho hợp protocol ChannelAdapter."""
        return {}

    async def download_attachment(self, attachment: Attachment) -> bytes:
        """Tải ảnh từ URL Zalo (URL công khai, không cần auth)."""
        url = attachment.ref.get("url", "")
        if not url:
            raise ValueError("Attachment không có URL.")
        resp = await self._http().get(url)
        if resp.status_code != 200:
            raise RuntimeError(f"download_attachment lỗi {resp.status_code}")
        return resp.content
