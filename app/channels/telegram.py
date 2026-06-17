"""TelegramAdapter — hiện thực ChannelAdapter qua Telegram Bot API (webhook mode).

Dùng httpx gọi thẳng Bot API thay vì aiogram: nhẹ, không cần session lifecycle, và
**test được** bằng httpx.MockTransport. Orchestrator chỉ thấy interface ChannelAdapter
nên có thể đổi sang aiogram/Slack sau mà không ảnh hưởng FSM.

Inbound: parse update raw (message text hoặc callback_query bấm nút) → InboundMessage.
Outbound: send (kèm inline keyboard) + answer_callback (tắt spinner trên client).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.channels.base import Button, InboundMessage

log = logging.getLogger("luna.telegram")

_API_BASE = "https://api.telegram.org"
_MAX_LEN = 4000  # Telegram giới hạn 4096/tin — chừa biên.


@dataclass
class TelegramAdapter:
    token: str
    api_base: str = _API_BASE
    client: httpx.AsyncClient | None = None
    name: str = "telegram"

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

    # ----- Inbound -----
    def parse_inbound(self, raw: dict) -> InboundMessage:
        """Update raw → InboundMessage. Hỗ trợ tin text và callback (bấm nút)."""
        if "callback_query" in raw:
            cb = raw["callback_query"]
            chat = cb.get("message", {}).get("chat", {})
            return InboundMessage(
                platform=self.name,
                platform_user_id=str(cb["from"]["id"]),
                text=cb.get("data", ""),
                callback_data=cb.get("data"),
                chat_id=str(chat.get("id", cb["from"]["id"])),
                raw=raw,
            )
        msg = raw.get("message") or raw.get("edited_message") or {}
        return InboundMessage(
            platform=self.name,
            platform_user_id=str(msg.get("from", {}).get("id", "")),
            text=msg.get("text", "") or "",
            callback_data=None,
            chat_id=str(msg.get("chat", {}).get("id", "")),
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
        """Gửi tin (chunk nếu dài). Inline keyboard chỉ gắn vào chunk cuối."""
        chunks = [text[i : i + _MAX_LEN] for i in range(0, len(text), _MAX_LEN)] or [""]
        result: dict = {}
        for idx, chunk in enumerate(chunks):
            payload: dict = {"chat_id": platform_user_id, "text": chunk}
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
