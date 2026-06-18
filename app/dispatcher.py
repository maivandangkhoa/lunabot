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
import re
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.admin_commands import HELP_TEXT, handle_command, is_command
from app.channels.base import Button, ChannelAdapter
from app.models import Repository, Request, RequestStatus, User, UserRole
from app.onboarding import get_user_by_platform, link_user
from app.orchestrator import BLOCKING_STATUSES as _BLOCKING
from app.orchestrator import Orchestrator, cb, parse_cb

log = logging.getLogger("luna.dispatcher")

_TEXT_ACTIVE = (RequestStatus.CLARIFYING, RequestStatus.VERIFY)
_W_CLEAR = {"/clear", "/new", "/reset"}     # huỷ request đang mở → mở session mới

# Từ khoá text thay cho bấm nút (kênh add-on như Google Chat không route click về endpoint).
_W_CONFIRM = {"ok", "confirm", "duyệt", "duyet", "đồng ý", "dong y", "yes", "y", "ừ", "u"}
_W_EDIT = {"sửa", "sua", "chỉnh", "chinh", "edit", "fix"}
_W_CANCEL = {"huỷ", "huy", "hủy", "cancel", "bỏ", "bo", "stop"}
_W_VERIFY_OK = {"đạt", "dat", "ok", "pass", "duyệt", "duyet", "done", "xong", "good"}
_W_REJECT = {"từ chối", "tu choi", "reject", "no", "không", "khong"}
# Hợp của mọi từ khoá hành động — chặn tin thường (vd "fix bug #123") lọt vào nhánh hành động.
_W_ANY = _W_CONFIRM | _W_EDIT | _W_CANCEL | _W_VERIFY_OK | _W_REJECT

# Cho phép nhắm tường minh "ok #12" → tách số request khỏi câu trước khi khớp từ khoá.
_REQ_ID_RE = re.compile(r"#(\d+)")
# action → nhãn nút khi hỏi lại lúc nhập nhằng (nhiều việc cùng khớp 1 từ khoá).
_ACTION_VERB = {
    "confirm": "✅ Duyệt KH", "reject": "✏️ Sửa KH", "cancel": "❌ Huỷ",
    "verify_ok": "✅ Xác nhận đạt", "mgr_approve": "✅ Cho merge", "mgr_reject": "❌ Từ chối merge",
}


def _keyword_action(word: str, status: RequestStatus) -> str | None:
    """Map từ khoá → action hợp lệ cho TỪNG trạng thái. None nếu không khớp."""
    if status == RequestStatus.PLAN_REVIEW:
        if word in _W_CONFIRM: return "confirm"
        if word in _W_EDIT:    return "reject"
        if word in _W_CANCEL:  return "cancel"
    elif status == RequestStatus.VERIFY:
        if word in _W_VERIFY_OK: return "verify_ok"
        if word in _W_CANCEL:    return "cancel"
    elif status == RequestStatus.AWAIT_MANAGER:
        if word in _W_CONFIRM: return "mgr_approve"
        if word in _W_REJECT:  return "mgr_reject"
    return None

# Khoá theo user: serialize các event của cùng 1 người (mỗi event là 1 task nền + DB
# session riêng) → tránh đua giữa /start (link) và tin kế tiếp, và tránh tạo request trùng.
_user_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


async def handle_channel_update(db: Session, adapter: ChannelAdapter, github, raw: dict,
                                bot_id: int | None = None) -> None:
    """Parse update; nếu đang bận xử lý tin trước của CÙNG user (Claude đang chạy) thì báo
    bận + BỎ QUA tin này (xử lý trễ sẽ sai ngữ cảnh). Ngược lại xử lý dưới khoá.

    `bot_id`: bot riêng mà inbound thuộc về (None = bot Luna chung). Cô lập tenant — cùng 1
    tài khoản chat nói với nhiều bot khác tenant không bị lẫn user.

    Khoá chỉ bị giữ trong lúc chạy việc nặng (ANALYZING/EXECUTING). Lúc chờ user trả lời
    (CLARIFYING/PLAN_REVIEW/VERIFY) khoá đã nhả → tin mới được xử lý bình thường.
    """
    inbound = adapter.parse_inbound(raw)
    # Trong group mà tin KHÔNG nhắm tới bot (không @mention/command/reply) → bỏ qua im lặng.
    if inbound.is_group and not inbound.addressed:
        return
    reply_to = inbound.chat_id or inbound.platform_user_id
    lock = _user_locks[f"{bot_id}:{adapter.name}:{inbound.platform_user_id}"]
    if lock.locked():
        log.info("user %s đang bận — bỏ qua tin mới", inbound.platform_user_id)
        await adapter.send(reply_to,
                           "⏳ Em đang xử lý việc trước, xong em báo ngay. "
                           "Gửi lại nội dung này sau khi em xong nhé.")
        return
    async with lock:
        await _dispatch_inbound(db, adapter, github, inbound, bot_id)


async def _dispatch_inbound(db: Session, adapter: ChannelAdapter, github, inbound,
                            bot_id: int | None = None) -> None:
    text = (inbound.text or "").strip()
    reply_to = inbound.chat_id or inbound.platform_user_id

    # /start [<token>] — liên kết tài khoản. KHÔNG nhận token trong group (lộ token) → bảo DM.
    if text.startswith("/start"):
        if inbound.is_group:
            await adapter.send(reply_to,
                               "🔒 Hãy nhắn riêng (DM) cho bot để liên kết: /start <token>.")
            return
        await _handle_start(db, adapter, inbound.platform_user_id, text, bot_id)
        return

    user = get_user_by_platform(db, adapter.name, inbound.platform_user_id, bot_id)
    if user is None:
        log.warning("chưa liên kết: platform=%r pid=%r text=%r",
                    adapter.name, inbound.platform_user_id, text[:40])
        await adapter.send(reply_to,
                           "Anh/chị chưa liên kết tài khoản. Nhắn riêng bot: /start <token> (admin cấp).")
        return

    # Lệnh quản trị (/help, /whoami, /users, /invite, /role, /unlink) — tin text, không callback.
    # CHỈ trong DM: nhiều lệnh (/users, /invite) in token → tránh lộ trong group.
    _cmd0 = text.strip().split(maxsplit=1)[0].lower() if text.strip() else ""
    if inbound.callback_data is None and _cmd0 in _W_CLEAR:
        # /clear dùng được cả trong group (request có thể khởi tạo từ group) — không chặn DM-only.
        await Orchestrator(db, adapter, github=github).clear_open_request(user, reply_to=reply_to)
        return

    if inbound.callback_data is None and _cmd0 == "/ask":
        # /ask dùng được cả group (giống /clear) — chỉ-đọc, không lộ token.
        rest = text.split(maxsplit=1)
        await _handle_ask(db, Orchestrator(db, adapter, github=github), user,
                          rest[1].strip() if len(rest) > 1 else "", reply_to)
        return

    if inbound.callback_data is None and is_command(text):
        if inbound.is_group:
            await adapter.send(reply_to, "🔒 Lệnh quản trị chỉ dùng khi nhắn riêng (DM) cho bot.")
            return
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
            await orch.handle_callback(req, user, inbound.callback_data, reply_to=reply_to)
        return

    if not text and not inbound.attachments:
        return

    # Hành động bằng text (thay cho bấm nút) — ưu tiên trước khi coi là feedback/clarify.
    if text and await _try_text_action(db, orch, user, text, reply_to, inbound):
        return

    # Request đang mở để TƯƠNG TÁC bằng text. Group: 1 THREAD = 1 request (theo origin_chat_id),
    # bất kể chủ là ai → MANAGER làm rõ/feedback thay nhân viên trong cùng thread. DM: theo chính user.
    # (AWAIT_MANAGER/MERGED_DEV không thuộc _BLOCKING → coi như thread trống, cho tạo request mới.)
    active = _active_request(db, user, inbound)
    if active:
        is_mgr = user.role in (UserRole.MANAGER, UserRole.ADMIN)
        is_owner = user.id == active.requester_user_id
        if inbound.is_group and not is_owner and not is_mgr:
            # Thành viên khác trong thread đã có request → giữ quy tắc 1 thread 1 request.
            await adapter.send(reply_to,
                f"🧵 Thread này đang xử lý yêu cầu #{active.id}. Mở thread mới (hoặc DM bot) "
                "để gửi yêu cầu khác nhé.")
            return
        if active.status in _TEXT_ACTIVE:          # CLARIFYING → làm rõ; VERIFY → feedback (chủ/manager)
            await orch.handle_message(active, user, text, attachments=inbound.attachments)
        elif active.status == RequestStatus.PLAN_REVIEW:
            await adapter.send(reply_to,
                f"📋 Yêu cầu #{active.id} đang chờ duyệt kế hoạch. Trả lời: ok · sửa · huỷ.")
        else:                                       # NEW/ANALYZING/EXECUTING
            await adapter.send(reply_to,
                f"⏳ Em đang xử lý yêu cầu #{active.id} ({active.status.value}). "
                "Chờ em xong rồi gửi yêu cầu mới (thread mới) nhé.")
        return

    # Không còn request mở → tạo request mới (vào dự án đang chọn).
    chosen, repos = _resolve_active_repo(db, user)
    if not repos:
        await adapter.send(reply_to, "Tenant chưa có dự án nào. Admin thêm bằng /addrepo.")
        return
    if chosen is None:                          # nhiều repo + chưa chọn → bảo chọn
        lines = "\n".join(f"{i}. {r.repo_full_name}" for i, r in enumerate(repos, 1))
        await adapter.send(reply_to,
                           f"Tenant có nhiều dự án. Chọn trước bằng /repo <số|tên>:\n{lines}")
        return
    title = text.splitlines()[0][:200] if text else "(ảnh đính kèm)"
    await orch.create_request(chosen, user, title=title, body=text, attachments=inbound.attachments,
                              chat_id=inbound.chat_id, platform=adapter.name,
                              is_group=inbound.is_group)


def _active_request(db: Session, user: User, inbound) -> Request | None:
    """Request đang mở (BLOCKING) để tương tác bằng text. Group: theo THREAD (origin_chat_id) bất
    kể chủ là ai (cho manager làm rõ/feedback thay). DM: theo chính user. Đảm bảo 1 thread 1 request."""
    if inbound.is_group and inbound.chat_id:
        return db.scalars(
            select(Request).where(
                Request.tenant_id == user.tenant_id,
                Request.origin_chat_id == inbound.chat_id,
                Request.status.in_(_BLOCKING),
            ).order_by(Request.id.desc())
        ).first()
    return db.scalars(
        select(Request).where(
            Request.requester_user_id == user.id, Request.status.in_(_BLOCKING)
        ).order_by(Request.id.desc())
    ).first()


def _actionable(db: Session, user: User, word: str,
                *, group_chat_id: str | None = None) -> list[tuple[Request, str]]:
    """Mọi việc đang chờ mà từ khoá `word` áp dụng được: request PLAN_REVIEW/VERIFY của chính họ
    (vai requester) + AWAIT_MANAGER của tenant (vai manager) + (manager, trong group) PLAN_REVIEW/
    VERIFY của THREAD này — để manager thao tác 'đạt/sửa/huỷ' thay nhân viên. Trả (request, action)."""
    reqs = list(db.scalars(
        select(Request).where(
            Request.requester_user_id == user.id,
            Request.status.in_((RequestStatus.PLAN_REVIEW, RequestStatus.VERIFY)),
        ).order_by(Request.id.desc())
    ).all())
    if user.role in (UserRole.MANAGER, UserRole.ADMIN):
        reqs += db.scalars(
            select(Request).where(
                Request.tenant_id == user.tenant_id,
                Request.status == RequestStatus.AWAIT_MANAGER,
            ).order_by(Request.id.desc())
        ).all()
        if group_chat_id:
            reqs += db.scalars(
                select(Request).where(
                    Request.tenant_id == user.tenant_id,
                    Request.origin_chat_id == group_chat_id,
                    Request.status.in_((RequestStatus.PLAN_REVIEW, RequestStatus.VERIFY)),
                ).order_by(Request.id.desc())
            ).all()
    seen: set[int] = set()
    uniq = [r for r in reqs if not (r.id in seen or seen.add(r.id))]  # dedup, giữ thứ tự
    return [(r, act) for r in uniq if (act := _keyword_action(word, r.status))]


async def _try_text_action(db: Session, orch: Orchestrator, user: User, text: str,
                           reply_to: str, inbound=None) -> bool:
    """Map text từ khoá → hành động nút (cho kênh không route click, vd Google Chat add-on).

    Gom mọi việc actionable (requester + manager) rồi quyết: nhắm tường minh `ok #id`; đúng 1
    việc → làm luôn; nhiều việc cùng khớp → hỏi lại bằng nút (mỗi nút mang đúng req.id) thay vì
    đoán. Trả True nếu đã xử lý/đã hỏi. Text không khớp việc nào → False (feedback/làm rõ ở luồng cũ).
    """
    m = _REQ_ID_RE.search(text)
    target_id = int(m.group(1)) if m else None
    word = _REQ_ID_RE.sub("", text).strip().lower()   # bỏ '#12' trước khi khớp từ khoá
    if word not in _W_ANY:                             # không phải từ khoá → luồng cũ (tránh hijack)
        return False
    group_chat_id = inbound.chat_id if (inbound and inbound.is_group) else None
    cands = _actionable(db, user, word, group_chat_id=group_chat_id)

    if target_id is not None:                          # nhắm tường minh "ok #12"
        hit = next((c for c in cands if c[0].id == target_id), None)
        if hit is None:
            await orch.adapter.send(
                reply_to, f"⚠️ Yêu cầu #{target_id} không đang chờ '{word}' của anh/chị.")
            return True
        await orch.handle_callback(hit[0], user, cb(hit[1], hit[0].id), reply_to=reply_to)
        return True

    if not cands:                                      # không phải hành động → luồng cũ
        return False
    if len(cands) == 1:                                # rõ ràng → làm luôn
        req, action = cands[0]
        await orch.handle_callback(req, user, cb(action, req.id), reply_to=reply_to)
        return True

    # Nhập nhằng (>1 việc khớp) → hỏi lại; nút mang đúng cb(action, req.id) đi đường callback.
    buttons = [[Button(f"{_ACTION_VERB[act]} #{r.id}", cb(act, r.id))] for r, act in cands]
    await orch.adapter.send(
        reply_to, "🤔 Anh/chị có nhiều việc đang chờ — chọn việc cần áp dụng:", buttons)
    return True


def _resolve_active_repo(db: Session, user: User) -> tuple[Repository | None, list[Repository]]:
    """Repo để thao tác cho user: 1 repo → dùng luôn; nhiều → theo active_repo_id (None nếu
    chưa chọn). Trả (chosen, all_repos) để caller tự lo thông báo."""
    repos = list(db.scalars(
        select(Repository).where(Repository.tenant_id == user.tenant_id).order_by(Repository.id)
    ).all())
    if not repos:
        return None, []
    if len(repos) == 1:
        return repos[0], repos
    return next((r for r in repos if r.id == user.active_repo_id), None), repos


async def _handle_ask(db: Session, orch: Orchestrator, user: User, question: str,
                      reply_to: str) -> None:
    """/ask <câu hỏi> — hỏi-đáp CHỈ-ĐỌC về dự án đang chọn, KHÔNG tạo request/PR (không qua FSM)."""
    if not question:
        await orch.adapter.send(
            reply_to, "Cú pháp: /ask <câu hỏi về dự án>.\nVd: /ask dự án này dùng DB gì?")
        return
    chosen, repos = _resolve_active_repo(db, user)
    if not repos:
        await orch.adapter.send(reply_to, "Tenant chưa có dự án nào. Admin thêm bằng /addrepo.")
        return
    if chosen is None:
        lines = "\n".join(f"{i}. {r.repo_full_name}" for i, r in enumerate(repos, 1))
        await orch.adapter.send(
            reply_to, f"Có nhiều dự án — chọn trước bằng /repo <số|tên> rồi /ask lại:\n{lines}")
        return
    await orch.adapter.send(reply_to, "🔎 Em xem rồi trả lời ngay…")
    await orch.ask(chosen, user, question, reply_to=reply_to)


async def _handle_start(db: Session, adapter: ChannelAdapter, platform_user_id: str, text: str,
                        bot_id: int | None = None) -> None:
    parts = text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await adapter.send(platform_user_id,
                           "Chào mừng đến luna 🌙\nĐể liên kết: /start <token> (admin cấp cho anh/chị).")
        return
    user = link_user(db, parts[1].strip(), platform_user_id, platform=adapter.name, bot_id=bot_id)
    if user is None:
        await adapter.send(platform_user_id, "❌ Token không hợp lệ hoặc đã dùng.")
        return
    try:
        db.commit()
    except IntegrityError:
        # (platform, platform_user_id) đã tồn tại → tài khoản này đã liên kết bằng token khác.
        db.rollback()
        await adapter.send(platform_user_id, "Tài khoản này đã được liên kết rồi. Bạn có thể gửi yêu cầu luôn.")
        return
    await adapter.send(platform_user_id,
                       f"✅ Đã liên kết! Vai trò: {user.role.value}. "
                       f"Gửi yêu cầu bảo trì để bắt đầu.\n\n{HELP_TEXT}")


# Alias tương thích ngược: tên cũ thời chỉ-Telegram (tests/poller/main vẫn dùng được).
handle_telegram_update = handle_channel_update
