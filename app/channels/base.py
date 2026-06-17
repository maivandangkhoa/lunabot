"""ChannelAdapter — interface đa nền tảng chat.

Orchestrator/FSM chỉ nói chuyện qua interface này, không biết Telegram/Slack cụ thể.
MVP chỉ có TelegramAdapter (M3). Thêm Slack/Google Chat = thêm adapter, FSM không đổi.

Tham khảo pattern: {base,dispatcher,telegram}.py
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class InboundMessage:
    """Tin nhắn đến đã normalize từ update raw của platform."""

    platform: str
    platform_user_id: str
    text: str
    # Với callback (bấm nút) thì callback_data có giá trị; tin text thường thì None.
    callback_data: str | None = None
    chat_id: str | None = None
    raw: dict = field(default_factory=dict)


@dataclass
class Button:
    """Nút hành động (inline keyboard) — Confirm / Verify / Approve."""

    text: str
    callback_data: str


class ChannelAdapter(Protocol):
    """Interface mọi adapter phải hiện thực."""

    name: str

    def parse_inbound(self, raw: dict) -> InboundMessage:
        """Update raw của platform → InboundMessage chuẩn hoá."""
        ...

    async def send(
        self,
        platform_user_id: str,
        text: str,
        buttons: list[list[Button]] | None = None,
    ) -> Any:
        """Gửi tin (kèm inline buttons tuỳ chọn) tới user."""
        ...

    async def answer_callback(self, callback_id: str, text: str | None = None) -> Any:
        """Xác nhận đã xử lý 1 lần bấm nút (tránh spinner kẹt trên client)."""
        ...
