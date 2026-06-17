"""Recovery lúc app khởi động lại (deploy/restart).

Request ở trạng thái CHẠY (NEW/ANALYZING/EXECUTING) có tiến trình `claude` chạy nền; khi
container restart, tiến trình bị kill → không ai resume, request kẹt mãi (khoá in-memory
cũng mất). Khi startup: đánh dấu các request đó CANCELLED + báo nơi khởi tạo để user gửi lại.

Trạng thái CHỜ-user (CLARIFYING/PLAN_REVIEW/VERIFY) KHÔNG đụng: không có việc đang chạy,
session Claude vẫn persist (volume `.claude`) → tương tác kế tiếp `--resume` bình thường.
"""
from __future__ import annotations

import logging
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.channels.base import ChannelAdapter
from app.channels.google_chat import GoogleChatAdapter
from app.channels.telegram import TelegramAdapter
from app.config import Settings
from app.db import SessionLocal
from app.models import (
    EventDirection,
    EventKind,
    Request,
    RequestEvent,
    RequestStatus,
    User,
)

log = logging.getLogger("luna.recovery")

# Trạng thái có tiến trình Claude chạy nền (mất khi restart). CHỜ-user KHÔNG nằm đây.
_INTERRUPTED = (RequestStatus.NEW, RequestStatus.ANALYZING, RequestStatus.EXECUTING)

_NOTE = (
    "⚠️ Hệ thống vừa khởi động lại nên yêu cầu #{rid} đang xử lý dở bị gián đoạn. "
    "Em đã đóng nó — anh/chị gửi lại yêu cầu để em làm lại nhé."
)


def close_interrupted(db: Session) -> list[Request]:
    """Đánh dấu CANCELLED + ghi event cho mọi request kẹt ở trạng thái chạy. Commit & trả list."""
    reqs = list(db.scalars(select(Request).where(Request.status.in_(_INTERRUPTED))).all())
    for req in reqs:
        log.warning("recovery: đóng request %s kẹt ở %s (do restart)", req.id, req.status.value)
        req.status = RequestStatus.CANCELLED
        db.add(RequestEvent(
            request_id=req.id, kind=EventKind.SYSTEM, direction=EventDirection.OUT,
            payload_json={"recovery": "interrupted_by_restart"},
        ))
    if reqs:
        db.commit()
    return reqs


def _build_adapter(platform: str | None, settings: Settings) -> ChannelAdapter | None:
    if platform == "telegram" and settings.telegram_bot_token:
        return TelegramAdapter(token=settings.telegram_bot_token,
                               bot_username=settings.telegram_bot_username)
    if platform == "google_chat" and settings.google_chat_enabled:
        return GoogleChatAdapter.from_settings(settings)
    return None


def _requester_pid(db: Session, req: Request) -> str | None:
    user = db.get(User, req.requester_user_id)
    return user.platform_user_id if user else None


async def recover_interrupted_requests(
    settings: Settings,
    *,
    db: Session | None = None,
    adapter_factory: Callable[[str | None], ChannelAdapter | None] | None = None,
) -> int:
    """Đóng request kẹt + báo origin (best-effort). Trả số request đã xử lý.

    Notify lỗi KHÔNG được làm hỏng startup. `db`/`adapter_factory` cho phép inject khi test.
    """
    own_db = db is None
    db = db or SessionLocal()
    factory = adapter_factory or (lambda p: _build_adapter(p, settings))
    cache: dict[str | None, ChannelAdapter | None] = {}
    built: list[ChannelAdapter] = []
    try:
        reqs = close_interrupted(db)
        for req in reqs:
            target = req.origin_chat_id or _requester_pid(db, req)
            if not target:
                continue
            if req.origin_platform not in cache:
                cache[req.origin_platform] = factory(req.origin_platform)
                if cache[req.origin_platform] is not None:
                    built.append(cache[req.origin_platform])
            adapter = cache[req.origin_platform]
            if adapter is None:
                continue
            try:
                await adapter.send(target, _NOTE.format(rid=req.id))
            except Exception:  # noqa: BLE001 — notify best-effort
                log.exception("recovery: notify request %s lỗi", req.id)
        return len(reqs)
    finally:
        for adapter in built:
            try:
                await adapter.aclose()
            except Exception:  # noqa: BLE001
                pass
        if own_db:
            db.close()
