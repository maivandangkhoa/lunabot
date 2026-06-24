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
from app.channels.zalo import ZaloAdapter
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


def build_adapter(bot: Bot, settings=None) -> TelegramAdapter | ZaloAdapter:
    """Dựng adapter phù hợp cho 1 bot riêng (token giải mã từ DB)."""
    if bot.platform == "telegram":
        return TelegramAdapter(token=bot_token(bot, settings), bot_username=bot.username)
    if bot.platform == "zalo":
        return _build_zalo_adapter(bot, settings)
    raise ValueError(f"Bot #{bot.id} platform={bot.platform} chưa hỗ trợ route đa bot.")


def _build_zalo_adapter(bot: Bot, settings=None) -> ZaloAdapter:
    """Dựng ZaloAdapter từ Bot row (mode=own). Token lưu dạng JSON mã hoá Fernet."""
    import json
    s = settings or get_settings()
    raw = decrypt_token(bot.token_encrypted or "", s.bot_token_enc_key)
    try:
        creds = json.loads(raw)
    except Exception:  # noqa: BLE001
        raise ValueError(f"Bot #{bot.id}: token Zalo không đúng định dạng JSON.") from None
    return ZaloAdapter(
        app_id=creds.get("app_id", ""),
        app_secret=creds.get("app_secret", ""),
        access_token=creds.get("access_token", ""),
        refresh_token=creds.get("refresh_token"),
        oa_id=creds.get("oa_id"),
        name="zalo",
    )


def webhook_url(bot: Bot, settings=None) -> str:
    s = settings or get_settings()
    base = (s.public_base_url or "").rstrip("/")
    if bot.platform == "zalo":
        return f"{base}/webhook/zalo/{bot.id}"
    return f"{base}/webhook/telegram/{bot.id}"


async def register_webhook(bot: Bot, adapter: TelegramAdapter, settings=None) -> None:
    """setWebhook trỏ về endpoint đa bot kèm secret để xác thực inbound."""
    await adapter.set_webhook(webhook_url(bot, settings), secret_token=bot.webhook_secret)
