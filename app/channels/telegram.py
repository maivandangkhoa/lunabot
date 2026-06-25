"""TelegramAdapter — hiện thực ChannelAdapter qua Telegram Bot API (webhook mode).

Dùng httpx gọi thẳng Bot API thay vì aiogram: nhẹ, không cần session lifecycle, và
**test được** bằng httpx.MockTransport. Orchestrator chỉ thấy interface ChannelAdapter
nên có thể đổi sang aiogram/Slack sau mà không ảnh hưởng FSM.

Inbound: parse update raw (message text hoặc callback_query bấm nút) → InboundMessage.
Outbound: send (kèm inline keyboard) + answer_callback (tắt spinner trên client).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import httpx

from app.channels.base import Button, InboundMessage
from app.channels.formatting import format_for, split_chunks

log = logging.getLogger("luna.telegram")

_API_BASE = "https://api.telegram.org"
_MAX_LEN = 4000  # Telegram giới hạn 4096/tin — chừa biên.
_GROUP_TYPES = ("group", "supergroup")


@dataclass
class TelegramAdapter:
    token: str
    api_base: str = _API_BASE
    client: httpx.AsyncClient | None = None
    name: str = "telegram"
    # Định danh bot (nạp qua get_me lúc startup) — để nhận diện @mention/reply trong group.
    bot_username: str | None = None
    bot_id: int | None = None

    def _http(self) -> httpx.AsyncClient:
        if self.client is None:
            self.client = httpx.AsyncClient(base_url=self.api_base, timeout=30)
        return self.client

    async def aclose(self) -> None:
        if self.client is not None:
            await self.client.aclose()
            self.client = None

    async def _api(self, method: str, payload: dict) -> dict:
        resp = await self._http().post(f"/bot{self.token}/{method}", json=payload)
        data = resp.json()
        if not data.get("ok"):
            log.warning("telegram %s lỗi: %s", method, data.get("description"))
        return data

    async def get_me(self) -> dict:
        """Lấy username/id của bot (cache vào self) — để nhận diện @mention/reply trong group."""
        data = await self._api("getMe", {})
        me = data.get("result", {})
        if me:
            self.bot_username = me.get("username") or self.bot_username
            self.bot_id = me.get("id") or self.bot_id
        return me

    # ----- Inbound -----
    def _strip_mention(self, text: str) -> str:
        """Bỏ '@<bot_username>' khỏi text (kể cả đuôi command /help@Bot → /help)."""
        if not text or not self.bot_username:
            return text.strip()
        return re.sub(rf"@{re.escape(self.bot_username)}\b", "", text,
                      flags=re.IGNORECASE).strip()

    def parse_inbound(self, raw: dict) -> InboundMessage:
        """Update raw → InboundMessage. Hỗ trợ tin text và callback (bấm nút).

        Trong group: set is_group, bỏ @mention khỏi text, và addressed=True chỉ khi tin nhắm
        tới bot (@mention / command / reply tới bot / bấm nút).
        """
        if "callback_query" in raw:
            cb = raw["callback_query"]
            chat = cb.get("message", {}).get("chat", {})
            return InboundMessage(
                platform=self.name,
                platform_user_id=str(cb["from"]["id"]),
                text=cb.get("data", ""),
                callback_data=cb.get("data"),
                chat_id=str(chat.get("id", cb["from"]["id"])),
                is_group=chat.get("type") in _GROUP_TYPES,
                addressed=True,          # bấm nút luôn là nhắm tới bot
                language_code=cb["from"].get("language_code"),
                raw=raw,
            )
        msg = raw.get("message") or raw.get("edited_message") or {}
        chat = msg.get("chat", {})
        is_group = chat.get("type") in _GROUP_TYPES
        raw_text = msg.get("text", "") or ""
        mentioned = bool(self.bot_username) and f"@{self.bot_username}".lower() in raw_text.lower()
        is_cmd = raw_text.startswith("/")
        replied = (self.bot_id is not None
                   and msg.get("reply_to_message", {}).get("from", {}).get("id") == self.bot_id)
        return InboundMessage(
            platform=self.name,
            platform_user_id=str(msg.get("from", {}).get("id", "")),
            text=self._strip_mention(raw_text),
            callback_data=None,
            chat_id=str(chat.get("id", "")),
            is_group=is_group,
            addressed=(not is_group) or mentioned or is_cmd or replied,
            language_code=msg.get("from", {}).get("language_code"),
            raw=raw,
        )

    @staticmethod
    def callback_id(raw: dict) -> str | None:
        cb = raw.get("callback_query")
        return cb.get("id") if cb else None

    # ----- Outbound -----
    def _keyboard(self, buttons: list[list[Button]] | None) -> dict | None:
        if not buttons:
            return None
        return {
            "inline_keyboard": [
                [{"text": b.text, "callback_data": b.callback_data} for b in row]
                for row in buttons
            ]
        }

    async def send(
        self,
        platform_user_id: str,
        text: str,
        buttons: list[list[Button]] | None = None,
    ) -> dict:
        """Gửi tin (chunk nếu dài). Inline keyboard chỉ gắn vào chunk cuối.

        Markdown của bot → Telegram HTML (`parse_mode=HTML`) qua format_for; chunk ở ranh giới
        dòng để không cắt giữa thẻ inline."""
        body, parse_mode = format_for(self.name, text)
        chunks = split_chunks(body, _MAX_LEN)
        result: dict = {}
        for idx, chunk in enumerate(chunks):
            payload: dict = {"chat_id": platform_user_id, "text": chunk}
            if parse_mode:
                payload["parse_mode"] = parse_mode
            if idx == len(chunks) - 1:
                kb = self._keyboard(buttons)
                if kb:
                    payload["reply_markup"] = kb
            result = await self._api("sendMessage", payload)
        return result

    async def answer_callback(self, callback_id: str, text: str | None = None) -> dict:
        payload: dict = {"callback_query_id": callback_id}
        if text:
            payload["text"] = text
        return await self._api("answerCallbackQuery", payload)

    # ----- Long-polling -----
    async def get_updates(self, offset: int | None = None, timeout: int = 25) -> list[dict]:
        """Long-poll getUpdates. Chỉ lấy message + callback_query."""
        payload: dict = {"timeout": timeout, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            payload["offset"] = offset
        resp = await self._http().post(
            f"/bot{self.token}/getUpdates", json=payload, timeout=timeout + 10
        )
        data = resp.json()
        return data.get("result", []) if data.get("ok") else []

    async def delete_webhook(self) -> dict:
        """Xoá webhook nếu có (getUpdates và webhook loại trừ nhau)."""
        return await self._api("deleteWebhook", {"drop_pending_updates": False})

    async def set_webhook(self, url: str, secret_token: str | None = None) -> dict:
        """Đăng ký webhook cho bot riêng (provisioning). `secret_token` → Telegram gửi kèm
        header X-Telegram-Bot-Api-Secret-Token để ta xác thực inbound."""
        payload: dict = {"url": url, "allowed_updates": ["message", "callback_query"]}
        if secret_token:
            payload["secret_token"] = secret_token
        return await self._api("setWebhook", payload)
