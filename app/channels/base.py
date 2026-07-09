"""ChannelAdapter — interface đa nền tảng chat.

Orchestrator/FSM chỉ nói chuyện qua interface này, không biết Telegram/Slack cụ thể.
MVP chỉ có TelegramAdapter (M3). Thêm Slack/Google Chat = thêm adapter, FSM không đổi.

Tham khảo pattern: {base,dispatcher,telegram}.py
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class Attachment:
    """Ảnh/tệp đính kèm đã normalize. `ref` giữ thông tin để adapter tải về (mỗi platform khác)."""

    file_name: str
    content_type: str
    ref: dict = field(default_factory=dict)

    @property
    def is_image(self) -> bool:
        return self.content_type.startswith("image/")


@dataclass
class InboundMessage:
    """Tin nhắn đến đã normalize từ update raw của platform."""

    platform: str
    platform_user_id: str
    text: str
    # Với callback (bấm nút) thì callback_data có giá trị; tin text thường thì None.
    callback_data: str | None = None
    chat_id: str | None = None
    # True nếu tin đến từ group/space nhiều người (vs DM 1:1). FSM dùng để trả lời công khai
    # trong group và quyết notify manager ở group hay DM.
    is_group: bool = False
    # True nếu tin nhắm tới bot (DM, @mention, command, reply, hoặc bấm nút). Trong group mà
    # KHÔNG addressed thì dispatcher bỏ qua (tránh biến mọi tin trong group thành request).
    addressed: bool = True
    # Mã ngôn ngữ client chat khai báo (vd Telegram "en"/"vi"/"ko"); None nếu platform không có.
    # Dispatcher dùng để suy & lưu User.language → bot trả lời đúng ngôn ngữ người dùng.
    language_code: str | None = None
    attachments: list[Attachment] = field(default_factory=list)
    # True nếu update KHÔNG phải tin của người dùng cần xử lý (vd platform echo lại tin của
    # chính bot, event hệ thống). Dispatcher bỏ qua hoàn toàn — tránh loop bot tự trả lời mình.
    ignore: bool = False
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
        destination: str,
        text: str,
        buttons: list[list[Button]] | None = None,
    ) -> Any:
        """Gửi tin (kèm inline buttons tuỳ chọn) tới `destination` — ID **đích chat**, không
        nhất thiết là user: DM (user id / DM space) hoặc group (group chat_id / space ROOM)."""
        ...

    async def answer_callback(self, callback_id: str, text: str | None = None) -> Any:
        """Xác nhận đã xử lý 1 lần bấm nút (tránh spinner kẹt trên client)."""
        ...

    async def download_attachment(self, attachment: Attachment) -> bytes:
        """Tải nội dung attachment về (bytes). Adapter nào hỗ trợ ảnh mới hiện thực."""
        ...
