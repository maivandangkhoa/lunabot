"""Recovery lúc app khởi động lại (deploy/restart).

Request ở trạng thái CHẠY (NEW/ANALYZING/EXECUTING) có tiến trình `claude` chạy nền; khi
container restart, tiến trình bị kill → không ai resume, request kẹt mãi (khoá in-memory
cũng mất). Khi startup: đánh dấu các request đó CANCELLED + báo nơi khởi tạo để user gửi lại.

Trạng thái CHỜ-user (CLARIFYING/PLAN_REVIEW/VERIFY) KHÔNG đụng: không có việc đang chạy,
session Claude vẫn persist (volume `.claude`) → tương tác kế tiếp `--resume` bình thường.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.channels.base import ChannelAdapter
from app.channels.google_chat import GoogleChatAdapter
from app.channels.messenger import MessengerAdapter
from app.channels.telegram import TelegramAdapter
from app.channels.zalo import ZaloAdapter
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
from app.web.i18n import set_lang, t

log = logging.getLogger("luna.recovery")

# Trạng thái có tiến trình Claude chạy nền (mất khi restart). CHỜ-user KHÔNG nằm đây.
_INTERRUPTED = (RequestStatus.NEW, RequestStatus.ANALYZING, RequestStatus.EXECUTING)


def close_interrupted(db: Session) -> list[Request]:
    """Đánh dấu CANCELLED + ghi event cho request kẹt ở trạng thái chạy. Commit & trả list ĐÃ HUỶ.

    Ngoại lệ preview-first: request đang rework (EXECUTING nhưng ĐÃ có dev_merge_sha → đang giữ
    slot dev với bản đã merge trước đó) KHÔNG huỷ — huỷ mà không revert sẽ để thay đổi lửng lơ
    trên dev rồi rò lên main. Đưa về VERIFY (UAT trên bản dev cũ đã tốt), user tự bấm 'Cần sửa' lại."""
    reqs = list(db.scalars(select(Request).where(Request.status.in_(_INTERRUPTED))).all())
    cancelled: list[Request] = []
    for req in reqs:
        if req.dev_merge_sha is not None:  # holder đang rework → giữ slot, về UAT
            log.warning("recovery: request %s rework bị ngắt (restart) → về VERIFY (giữ dev)", req.id)
            req.status = RequestStatus.VERIFY
            db.add(RequestEvent(
                request_id=req.id, kind=EventKind.SYSTEM, direction=EventDirection.OUT,
                payload_json={"recovery": "rework_interrupted_back_to_verify"}))
            continue
        log.warning("recovery: đóng request %s kẹt ở %s (do restart)", req.id, req.status.value)
        req.status = RequestStatus.CANCELLED
        db.add(RequestEvent(
            request_id=req.id, kind=EventKind.SYSTEM, direction=EventDirection.OUT,
            payload_json={"recovery": "interrupted_by_restart"},
        ))
        cancelled.append(req)
    if reqs:
        db.commit()
    return cancelled


def _build_adapter(platform: str | None, settings: Settings) -> ChannelAdapter | None:
    if platform == "telegram" and settings.telegram_bot_token:
        return TelegramAdapter(token=settings.telegram_bot_token,
                               bot_username=settings.telegram_bot_username)
    if platform == "google_chat" and settings.google_chat_enabled:
        return GoogleChatAdapter.from_settings(settings)
    if platform == "messenger" and settings.messenger_enabled:
        return MessengerAdapter.from_settings(settings)
    if platform == "zalo" and settings.zalo_enabled:
        return ZaloAdapter.from_settings(settings)
    return None


def _requester_pid(db: Session, req: Request) -> str | None:
    user = db.get(User, req.requester_user_id)
    return user.platform_user_id if user else None


async def rekick_pending_deploys(settings: Settings, *, db: Session | None = None) -> int:
    """Sau restart: tiếp tục deploy-gate cho request kẹt ở MERGED_DEV (background task chết khi
    restart). Re-poll theo `dev_merge_sha` đã lưu — idempotent: deploy đã xong thì đi tiếp ngay.

    Spawn task có db/adapter/github RIÊNG (xem post_deploy.verify_after_dev_merge)."""
    from app.post_deploy import verify_after_dev_merge

    own = db is None
    db = db or SessionLocal()
    try:
        reqs = list(db.scalars(
            select(Request).where(Request.status == RequestStatus.MERGED_DEV)).all())
        for req in reqs:
            asyncio.create_task(verify_after_dev_merge(req.id, settings=settings))
        return len(reqs)
    finally:
        if own:
            db.close()


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
            requester = db.get(User, req.requester_user_id)
            target = req.origin_chat_id or (requester.platform_user_id if requester else None)
            if not target:
                continue
            if req.origin_platform not in cache:
                cache[req.origin_platform] = factory(req.origin_platform)
                if cache[req.origin_platform] is not None:
                    built.append(cache[req.origin_platform])
            adapter = cache[req.origin_platform]
            if adapter is None:
                continue
            set_lang(requester.language if requester else None)  # trả lời đúng ngôn ngữ requester
            try:
                await adapter.send(target, t("recovery.interrupted", rid=req.id))
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
