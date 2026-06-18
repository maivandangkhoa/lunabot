"""Bot registry — route đa bot trong 1 process luna (shared instance).

Mỗi bot riêng (mode="own") có token + webhook riêng. Endpoint /webhook/telegram/{bot_id}
dùng registry để: lấy Bot, giải mã token, dựng adapter đúng, và (lúc provisioning) đăng ký
webhook. Bot Luna chung (mode="shared") KHÔNG đi qua đây — vẫn dùng adapter toàn cục như cũ.

Token chỉ giải mã trong bộ nhớ, KHÔNG log.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.channels.telegram import TelegramAdapter
from app.config import get_settings
from app.models import Bot
from app.token_crypto import decrypt_token

log = logging.getLogger("luna.bot_registry")


def get_bot(db: Session, bot_id: int) -> Bot | None:
    return db.get(Bot, bot_id)


def bot_token(bot: Bot, settings=None) -> str:
    """Token plaintext của bot riêng (giải mã). Raise nếu thiếu key/token."""
    s = settings or get_settings()
    if not bot.token_encrypted:
        raise ValueError(f"Bot #{bot.id} không có token (mode={bot.mode}).")
    return decrypt_token(bot.token_encrypted, s.bot_token_enc_key)


def build_adapter(bot: Bot, settings=None) -> TelegramAdapter:
    """Dựng TelegramAdapter cho 1 bot riêng (token giải mã + username để nhận @mention group)."""
    if bot.platform != "telegram":
        raise ValueError(f"Bot #{bot.id} platform={bot.platform} chưa hỗ trợ route đa bot.")
    return TelegramAdapter(token=bot_token(bot, settings), bot_username=bot.username)


def webhook_url(bot: Bot, settings=None) -> str:
    s = settings or get_settings()
    base = (s.public_base_url or "").rstrip("/")
    return f"{base}/webhook/telegram/{bot.id}"


async def register_webhook(bot: Bot, adapter: TelegramAdapter, settings=None) -> None:
    """setWebhook trỏ về endpoint đa bot kèm secret để xác thực inbound."""
    await adapter.set_webhook(webhook_url(bot, settings), secret_token=bot.webhook_secret)
