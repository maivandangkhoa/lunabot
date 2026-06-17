"""Dispatcher — route 1 update chat đã chuẩn hoá vào Orchestrator.

Channel-agnostic: nhận `ChannelAdapter` bất kỳ (Telegram/Google Chat). Tách khỏi FastAPI
để test trực tiếp (không cần HTTP). Phân biệt:
- `/start <token>` → liên kết tài khoản.
- callback (bấm nút, callback_data="action:req_id") → handle_callback.
- text thường → request đang mở của user (CLARIFYING/VERIFY), hoặc tạo request mới
  nếu tenant có đúng 1 repo.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin_commands import handle_command, is_command
from app.channels.base import ChannelAdapter
from app.models import Repository, Request, RequestStatus, User, UserRole
from app.onboarding import get_user_by_platform, link_user
from app.orchestrator import Orchestrator, cb, parse_cb

log = logging.getLogger("luna.dispatcher")

_TEXT_ACTIVE = (RequestStatus.CLARIFYING, RequestStatus.VERIFY)
# Trạng thái "đang bận với user" → chặn tạo request mới (1 user/1 request đang chạy).
# AWAIT_MANAGER/MERGED_DEV KHÔNG nằm đây: phần của requester đã xong, chỉ chờ manager
# → không được chặn requester gửi yêu cầu khác.
_BLOCKING = (
    RequestStatus.NEW, RequestStatus.ANALYZING, RequestStatus.CLARIFYING,
    RequestStatus.PLAN_REVIEW, RequestStatus.EXECUTING, RequestStatus.VERIFY,
)

# Từ khoá text thay cho bấm nút (kênh add-on như Google Chat không route click về endpoint).
_W_CONFIRM = {"ok", "confirm", "duyệt", "duyet", "đồng ý", "dong y", "yes", "y", "ừ", "u"}
_W_EDIT = {"sửa", "sua", "chỉnh", "chinh", "edit", "fix"}
_W_CANCEL = {"huỷ", "huy", "hủy", "cancel", "bỏ", "bo", "stop"}
_W_VERIFY_OK = {"đạt", "dat", "ok", "pass", "duyệt", "duyet", "done", "xong", "good"}
_W_REJECT = {"từ chối", "tu choi", "reject", "no", "không", "khong"}

# Khoá theo user: serialize các event của cùng 1 người (mỗi event là 1 task nền + DB
# session riêng) → tránh đua giữa /start (link) và tin kế tiếp, và tránh tạo request trùng.
_user_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


async def handle_channel_update(db: Session, adapter: ChannelAdapter, github, raw: dict) -> None:
    """Parse update; nếu đang bận xử lý tin trước của CÙNG user (Claude đang chạy) thì báo
    bận + BỎ QUA tin này (xử lý trễ sẽ sai ngữ cảnh). Ngược lại xử lý dưới khoá.

    Khoá chỉ bị giữ trong lúc chạy việc nặng (ANALYZING/EXECUTING). Lúc chờ user trả lời
    (CLARIFYING/PLAN_REVIEW/VERIFY) khoá đã nhả → tin mới được xử lý bình thường.
    """
    inbound = adapter.parse_inbound(raw)
    lock = _user_locks[f"{adapter.name}:{inbound.platform_user_id}"]
    if lock.locked():
        log.info("user %s đang bận — bỏ qua tin mới", inbound.platform_user_id)
        await adapter.send(inbound.platform_user_id,
                           "⏳ Em đang xử lý việc trước, xong em báo ngay. "
                           "Gửi lại nội dung này sau khi em xong nhé.")
        return
    async with lock:
        await _dispatch_inbound(db, adapter, github, inbound)


async def _dispatch_inbound(db: Session, adapter: ChannelAdapter, github, inbound) -> None:
    text = (inbound.text or "").strip()

    # /start [<token>] — liên kết tài khoản.
    if text.startswith("/start"):
        await _handle_start(db, adapter, inbound.platform_user_id, text)
        return

    user = get_user_by_platform(db, adapter.name, inbound.platform_user_id)
    if user is None:
        log.warning("chưa liên kết: platform=%r pid=%r text=%r",
                    adapter.name, inbound.platform_user_id, text[:40])
        await adapter.send(inbound.platform_user_id,
                           "Anh/chị chưa liên kết tài khoản. Dùng /start <token> (admin cấp).")
        return

    # Lệnh quản trị (/help, /whoami, /users, /invite, /role, /unlink) — tin text, không callback.
    if inbound.callback_data is None and is_command(text):
        await handle_command(db, adapter, user, text)
        return

    orch = Orchestrator(db, adapter, github=github)

    # Callback (bấm nút).
    if inbound.callback_data and parse_cb(inbound.callback_data):
        cbid = getattr(adapter, "callback_id", lambda r: None)(inbound.raw)
        if cbid:
            await adapter.answer_callback(cbid)
        _, rid = parse_cb(inbound.callback_data)
        req = db.get(Request, rid)
        if req and req.tenant_id == user.tenant_id:
            await orch.handle_callback(req, user, inbound.callback_data)
        return

    if not text and not inbound.attachments:
        return

    # Hành động bằng text (thay cho bấm nút) — ưu tiên trước khi coi là feedback/clarify.
    if text and await _try_text_action(db, orch, user, text):
        return

    # Mỗi user chỉ 1 request ĐANG TƯƠNG TÁC tại một thời điểm. Nếu đang có:
    # xử lý theo trạng thái thay vì tạo mới. (AWAIT_MANAGER/MERGED_DEV không tính → cho tạo mới.)
    open_req = db.scalars(
        select(Request).where(
            Request.requester_user_id == user.id, Request.status.in_(_BLOCKING)
        ).order_by(Request.id.desc())
    ).first()
    if open_req:
        if open_req.status in _TEXT_ACTIVE:        # CLARIFYING → làm rõ; VERIFY → feedback sửa
            await orch.handle_message(open_req, user, text, attachments=inbound.attachments)
        elif open_req.status == RequestStatus.PLAN_REVIEW:
            await adapter.send(user.platform_user_id,
                f"📋 Yêu cầu #{open_req.id} đang chờ duyệt kế hoạch. Trả lời: ok · sửa · huỷ.")
        else:                                       # NEW/ANALYZING/EXECUTING
            await adapter.send(user.platform_user_id,
                f"⏳ Em đang xử lý yêu cầu #{open_req.id} ({open_req.status.value}). "
                "Chờ em xong rồi gửi yêu cầu mới nhé.")
        return

    # Không còn request mở → tạo request mới.
    repos = db.scalars(select(Repository).where(Repository.tenant_id == user.tenant_id)).all()
    if len(repos) == 1:
        title = text.splitlines()[0][:200] if text else "(ảnh đính kèm)"
        await orch.create_request(repos[0], user, title=title, body=text,
                                  attachments=inbound.attachments)
    elif not repos:
        await adapter.send(user.platform_user_id, "Tenant chưa có repo nào được cấu hình.")
    else:
        names = ", ".join(r.repo_full_name for r in repos)
        await adapter.send(user.platform_user_id,
                           f"Tenant có nhiều repo ({names}). MVP: liên hệ admin để chọn repo.")


async def _try_text_action(db: Session, orch: Orchestrator, user: User, text: str) -> bool:
    """Map text từ khoá → hành động nút (cho kênh không route click, vd Google Chat add-on).

    Trả True nếu đã xử lý như 1 hành động. PLAN_REVIEW/VERIFY của requester + AWAIT_MANAGER
    của manager. Text khác (feedback sửa, làm rõ) rơi xuống luồng cũ.
    """
    word = text.strip().lower()
    req = db.scalars(
        select(Request).where(
            Request.requester_user_id == user.id,
            Request.status.in_((RequestStatus.PLAN_REVIEW, RequestStatus.VERIFY)),
        ).order_by(Request.id.desc())
    ).first()
    if req and req.status == RequestStatus.PLAN_REVIEW:
        action = ("confirm" if word in _W_CONFIRM else "reject" if word in _W_EDIT
                  else "cancel" if word in _W_CANCEL else None)
        if action:
            await orch.handle_callback(req, user, cb(action, req.id))
            return True
    elif req and req.status == RequestStatus.VERIFY:
        action = ("verify_ok" if word in _W_VERIFY_OK else "cancel" if word in _W_CANCEL else None)
        if action:
            await orch.handle_callback(req, user, cb(action, req.id))
            return True  # text khác → feedback sửa (luồng cũ)

    if user.role in (UserRole.MANAGER, UserRole.ADMIN):
        mreq = db.scalars(
            select(Request).where(
                Request.tenant_id == user.tenant_id,
                Request.status == RequestStatus.AWAIT_MANAGER,
            ).order_by(Request.id.desc())
        ).first()
        if mreq:
            action = ("mgr_approve" if word in _W_CONFIRM else "mgr_reject" if word in _W_REJECT
                      else None)
            if action:
                await orch.handle_callback(mreq, user, cb(action, mreq.id))
                return True
    return False


async def _handle_start(db: Session, adapter: ChannelAdapter, platform_user_id: str, text: str) -> None:
    parts = text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await adapter.send(platform_user_id,
                           "Chào mừng đến luna 🌙\nĐể liên kết: /start <token> (admin cấp cho anh/chị).")
        return
    user = link_user(db, parts[1].strip(), platform_user_id)
    if user is None:
        await adapter.send(platform_user_id, "❌ Token không hợp lệ hoặc đã dùng.")
        return
    db.commit()
    await adapter.send(platform_user_id,
                       f"✅ Đã liên kết! Vai trò: {user.role.value}. Gửi yêu cầu bảo trì để bắt đầu.")


# Alias tương thích ngược: tên cũ thời chỉ-Telegram (tests/poller/main vẫn dùng được).
handle_telegram_update = handle_channel_update
