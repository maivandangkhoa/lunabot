"""SlackAdapter — hiện thực ChannelAdapter qua Slack Web API (webhook mode).

Điểm khác Telegram/Google Chat:
- Webhook nhận 2 loại request:
  * Events API (JSON): tin nhắn text, app_mention trong channel.
  * Interactive components (form-encoded `payload=<JSON>`): bấm nút Block Kit.
- Outbound async: dùng `chat.postMessage` với Bot Token (xoxb-...).
- Buttons: Block Kit với `actions` element, callback_data lưu trong `value` của button.
- Signature verify: HMAC-SHA256 trên body với `X-Slack-Signature` + timestamp chống replay.
- answer_callback: Slack ack button qua HTTP response 200 đồng bộ (main.py xử lý); no-op ở đây.
- DM: channel ID bắt đầu `D`; public channel: `C`; private: `G`.
- Addressed: DM luôn True; channel thì chỉ khi @mention bot hoặc bấm nút.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.channels.base import Attachment, Button, InboundMessage
from app.channels.formatting import format_for, split_chunks

log = logging.getLogger("luna.slack")

_SLACK_API = "https://slack.com"
_MAX_LEN = 3000   # Slack text block giới hạn 3001 ký tự — chừa biên.
_REPLAY_WINDOW_S = 300   # 5 phút — chống replay attack

# Slack "nuốt" mọi tin bắt đầu bằng "/" thành slash-command của NÓ → lệnh bot (/start,
# /help…) không bao giờ tới. Bù lại: trên Slack user gõ lệnh KHÔNG dấu "/" (start <token>,
# help, lang en). Ở đây ta chuẩn hoá 2 chiều để dispatcher/FSM (vốn dựa vào "/") không đổi.
# Lệnh CÓ tham số: nhận ngay khi từ đầu khớp (phần sau là arg).
_CMD_ARG = frozenset({"start", "lang", "repo", "invite", "role", "addrepo", "ask"})
# Lệnh KHÔNG tham số: chỉ coi là lệnh khi nhắn ĐÚNG 1 từ → "help me fix…" vẫn là yêu cầu.
_CMD_NOARG = frozenset({"help", "whoami", "repos", "clear", "new", "reset", "users", "unlink"})
_CMD_ALL = _CMD_ARG | _CMD_NOARG
# Bỏ "/" ở đầu lệnh trong tin BOT gửi ra để hiển thị đúng dạng user gõ được trên Slack.
_DESLASH = re.compile(r"(?<![^\s(>])/(" + "|".join(sorted(_CMD_ALL)) + r")\b")


def _slack_to_slash(text: str) -> str:
    """Inbound: 'start <token>' → '/start <token>' để khớp dispatcher (chỉ khi khớp luật lệnh)."""
    stripped = text.lstrip()
    if not stripped or stripped.startswith("/"):
        return text
    parts = stripped.split(maxsplit=1)
    word = parts[0].lower()
    if word in _CMD_ARG or (word in _CMD_NOARG and len(parts) == 1):
        return "/" + stripped
    return text


@dataclass
class SlackAdapter:
    """Adapter Slack — shared workspace (env)."""

    bot_token: str
    signing_secret: str = ""
    api_base: str = _SLACK_API
    client: httpx.AsyncClient | None = None
    name: str = "slack"
    # bot_user_id để nhận diện @mention trong channel
    bot_user_id: str | None = None

    @classmethod
    def from_settings(cls, settings=None) -> "SlackAdapter":
        from app.config import get_settings
        s = settings or get_settings()
        return cls(
            bot_token=s.slack_bot_token or "",
            signing_secret=s.slack_signing_secret or "",
        )

    def _http(self) -> httpx.AsyncClient:
        if self.client is None:
            self.client = httpx.AsyncClient(base_url=self.api_base, timeout=30)
        return self.client

    async def aclose(self) -> None:
        if self.client is not None:
            await self.client.aclose()
            self.client = None

    # ----- Auth verify (inbound) -----
    def verify_signature(self, body: bytes, signature: str, timestamp: str) -> bool:
        """Xác minh HMAC-SHA256 chữ ký Slack gửi kèm webhook."""
        if not self.signing_secret:
            return True
        try:
            ts = int(timestamp)
        except (ValueError, TypeError):
            return False
        if abs(time.time() - ts) > _REPLAY_WINDOW_S:
            return False
        base = f"v0:{timestamp}:".encode() + body
        expected = "v0=" + hmac.new(
            self.signing_secret.encode(), base, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    # ----- Bot identity -----
    async def fetch_bot_user_id(self) -> str | None:
        """Lấy bot_user_id qua auth.test — cache vào self."""
        resp = await self._http().post(
            "/api/auth.test",
            headers={"Authorization": f"Bearer {self.bot_token}"},
        )
        data = resp.json()
        if data.get("ok"):
            self.bot_user_id = data.get("user_id")
        return self.bot_user_id

    # ----- Inbound -----
    def parse_inbound(self, raw: dict) -> InboundMessage:
        """Event raw Slack → InboundMessage.

        Hỗ trợ:
        - Events API: message / app_mention
        - Interactive components: button click (action_type=button)
        """
        # Button click (interactive payload đã parse JSON từ form-encoded)
        if "actions" in raw and "channel" in raw:
            return self._parse_action(raw)
        event = raw.get("event", {})
        etype = event.get("type", "")
        if etype in ("message", "app_mention"):
            # Slack echo lại chính tin bot vừa gửi (message.im có bot_id / subtype bot_message)
            # → PHẢI bỏ qua, nếu không bot tự trả lời mình → loop vô hạn. Cũng bỏ qua các event
            # sửa/xoá tin (message_changed/message_deleted...) vì không phải tin mới của user.
            subtype = event.get("subtype")
            is_bot = bool(event.get("bot_id")) or subtype == "bot_message" or (
                self.bot_user_id and event.get("user") == self.bot_user_id
            )
            # subtype hợp lệ cho tin user: None (text thường) và "file_share" (gửi kèm ảnh).
            is_system = subtype not in (None, "file_share")
            if is_bot or is_system:
                return InboundMessage(
                    platform=self.name, platform_user_id="", text="",
                    ignore=True, raw=raw,
                )
            return self._parse_message(event, raw)
        # Fallback an toàn
        return InboundMessage(
            platform=self.name,
            platform_user_id="",
            text="",
            raw=raw,
        )

    def _parse_message(self, event: dict, raw: dict) -> InboundMessage:
        uid = event.get("user") or event.get("bot_id") or ""
        channel = event.get("channel") or ""
        is_dm = channel.startswith("D")
        is_group = not is_dm
        # Bỏ @mention khỏi text (Slack giữ <@UBOTID> trong text)
        text = event.get("text") or ""
        if self.bot_user_id:
            text = text.replace(f"<@{self.bot_user_id}>", "").strip()
        # Slack chặn tin bắt đầu "/" → user gõ lệnh không dấu; khôi phục "/" cho dispatcher.
        text = _slack_to_slash(text)
        # app_mention luôn addressed; DM luôn addressed; channel message thường không
        addressed = is_dm or event.get("type") == "app_mention"
        # Ảnh đính kèm: Slack đặt trong event.files[] (cần scope files:read + Bearer token để tải).
        attachments: list[Attachment] = []
        for f in event.get("files") or []:
            mime = f.get("mimetype") or ""
            if not mime.startswith("image/"):
                continue
            url = f.get("url_private_download") or f.get("url_private") or ""
            if url:
                attachments.append(
                    Attachment(
                        file_name=f.get("name") or "image",
                        content_type=mime,
                        ref={"url_private": url},
                    )
                )
        return InboundMessage(
            platform=self.name,
            platform_user_id=uid,
            text=text,
            chat_id=channel,
            is_group=is_group,
            addressed=addressed,
            attachments=attachments,
            raw=raw,
        )

    def _parse_action(self, raw: dict) -> InboundMessage:
        """Block Kit button click."""
        uid = (raw.get("user") or {}).get("id") or ""
        channel = (raw.get("channel") or {}).get("id") or ""
        is_dm = channel.startswith("D")
        # Lấy value của action đầu tiên (convention: 1 block 1 action)
        actions = raw.get("actions") or []
        callback_data = None
        if actions:
            first = actions[0]
            callback_data = first.get("value") or first.get("action_id")
        return InboundMessage(
            platform=self.name,
            platform_user_id=uid,
            text=callback_data or "",
            callback_data=callback_data,
            chat_id=channel,
            is_group=not is_dm,
            addressed=True,   # bấm nút luôn nhắm tới bot
            raw=raw,
        )

    # ----- Outbound -----
    def _blocks(self, text: str, buttons: list[list[Button]] | None) -> list[dict]:
        """Dựng Block Kit: text section + optional actions block."""
        result: list[dict] = [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]
        if buttons:
            elements = [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": b.text, "emoji": True},
                    "value": b.callback_data,
                    "action_id": b.callback_data,
                }
                for row in buttons
                for b in row
            ]
            result.append({"type": "actions", "elements": elements})
        return result

    async def _api_post(self, endpoint: str, payload: dict) -> dict:
        resp = await self._http().post(
            f"/api/{endpoint}",
            json=payload,
            headers={"Authorization": f"Bearer {self.bot_token}"},
        )
        data = resp.json()
        if not data.get("ok"):
            log.warning("slack %s lỗi: %s", endpoint, data.get("error"))
        return data

    async def send(
        self,
        destination: str,
        text: str,
        buttons: list[list[Button]] | None = None,
    ) -> dict:
        """Gửi tin tới channel/DM (chunk nếu dài; blocks gắn chunk cuối)."""
        body, _ = format_for(self.name, text)
        # Hướng dẫn trong catalog viết "/start", "/help"… nhưng Slack không cho user GÕ "/".
        # Bỏ "/" ở các lệnh đã biết để user thấy đúng dạng gõ được (khớp _slack_to_slash).
        body = _DESLASH.sub(r"\1", body)
        chunks = split_chunks(body, _MAX_LEN)
        result: dict = {}
        for idx, chunk in enumerate(chunks):
            is_last = idx == len(chunks) - 1
            payload: dict[str, Any] = {"channel": destination}
            if is_last and buttons:
                payload["blocks"] = self._blocks(chunk, buttons)
            else:
                payload["blocks"] = [
                    {"type": "section", "text": {"type": "mrkdwn", "text": chunk}}
                ]
            result = await self._api_post("chat.postMessage", payload)
        return result

    async def answer_callback(self, callback_id: str, text: str | None = None) -> dict:
        """Slack ack button qua HTTP 200 trong webhook (main.py); adapter không cần làm gì."""
        return {}

    async def download_attachment(self, attachment: Attachment) -> bytes:
        """Tải file từ Slack (url_private cần Bearer token)."""
        url = attachment.ref.get("url_private") or attachment.ref.get("url")
        if not url:
            raise ValueError("Attachment Slack không có url_private.")
        resp = await self._http().get(
            url, headers={"Authorization": f"Bearer {self.bot_token}"}
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Slack download lỗi {resp.status_code}")
        return resp.content
