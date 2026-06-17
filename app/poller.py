"""Telegram long-polling — vòng lặp getUpdates → dispatcher.

Dùng khi TELEGRAM_MODE=polling (VM khoá port, không có domain/HTTPS). Một process chỉ
được chạy ĐÚNG 1 poller cho mỗi bot (getUpdates xung đột nếu nhiều). Mỗi update mở 1
DB session riêng để cô lập lỗi.
"""
from __future__ import annotations

import asyncio
import logging

from app.channels.telegram import TelegramAdapter
from app.config import get_settings
from app.db import SessionLocal
from app.dispatcher import handle_telegram_update
from app.github_app import GitHubApp

log = logging.getLogger("luna.poller")


async def run_polling(stop: asyncio.Event) -> None:
    s = get_settings()
    adapter = TelegramAdapter(token=s.telegram_bot_token or "",
                              bot_username=s.telegram_bot_username)
    try:
        await adapter.get_me()  # nạp bot_username/bot_id để nhận diện @mention/reply trong group
    except Exception as exc:  # noqa: BLE001
        log.warning("getMe lỗi (bỏ qua, group mention có thể không nhận diện): %s", exc)
    try:
        github = GitHubApp.from_settings()
    except Exception as exc:  # noqa: BLE001
        log.warning("GitHub App chưa cấu hình đủ (%s) — luồng EXECUTING sẽ báo lỗi.", exc)
        github = None

    try:
        await adapter.delete_webhook()
    except Exception as exc:  # noqa: BLE001
        log.warning("deleteWebhook lỗi (bỏ qua): %s", exc)

    offset: int | None = None
    log.info("Telegram long-polling bắt đầu")
    while not stop.is_set():
        try:
            updates = await adapter.get_updates(offset, timeout=25)
        except Exception as exc:  # noqa: BLE001
            log.warning("getUpdates lỗi: %s — thử lại sau 3s", exc)
            await asyncio.sleep(3)
            continue

        for u in updates:
            offset = u["update_id"] + 1  # ack: luôn tiến offset, kể cả update lỗi
            db = SessionLocal()
            try:
                await handle_telegram_update(db, adapter, github, u)
            except Exception:  # noqa: BLE001
                log.exception("xử lý update %s lỗi", u.get("update_id"))
            finally:
                db.close()

    await adapter.aclose()
    if github is not None:
        await github.aclose()
    log.info("Telegram long-polling dừng")
