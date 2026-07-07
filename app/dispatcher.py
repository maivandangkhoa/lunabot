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

from app import usage
from app.admin_commands import handle_command, help_text, is_command
from app.channels.base import Button, ChannelAdapter
from app.claude_runner import run_claude
from app.config import get_settings
from app.intent import Intent, classify_intent
from app.models import Repository, Request, RequestStatus, User, UserRole
from app.onboarding import AlreadyLinkedError, get_user_by_platform, link_user
from app.orchestrator import BLOCKING_STATUSES as _BLOCKING
from app.orchestrator import Orchestrator, cb, parse_cb
from app.textnorm import strip_symbols
from app.web.i18n import TEXTS, detect, normalize, set_lang, t

log = logging.getLogger("luna.dispatcher")

_TEXT_ACTIVE = (RequestStatus.CLARIFYING, RequestStatus.VERIFY)
# Lớp 2 (LLM hiểu câu tự nhiên) CHỈ chạy ở trạng thái cổng "thuần quyết định": user được kỳ
# vọng DUYỆT/TỪ CHỐI, không phải gõ nội dung. Ở CLARIFYING (trả lời làm rõ) và VERIFY (phản
# hồi sửa) văn bản tự do CHÍNH LÀ nội dung → giữ keyword-only, tránh tốn LLM + tránh hijack.
_LLM_GATE_STATUSES = (RequestStatus.PLAN_REVIEW, RequestStatus.AWAIT_MANAGER)
# Hành động KHÔNG hoàn tác → qua Lớp 2 (LLM) LUÔN xin xác nhận, bất kể độ chắc chắn. Chỉ
# `mgr_approve` (merge `main` = deploy production) thuộc nhóm này; còn lại (confirm trên dev,
# cancel/reject) còn cổng sau hoặc chỉ dừng việc nên cho làm thẳng khi LLM đủ chắc.
_IRREVERSIBLE = {"mgr_approve"}
_W_CLEAR = {"/clear", "/new", "/reset"}     # huỷ request đang mở → mở session mới
# Lệnh chỉ-đọc, không in token → an toàn dùng trong group (trả lời ngay trong thread).
# Các lệnh in token / sửa dữ liệu (/users, /invite, /role, /unlink, /addrepo) vẫn DM-only.
_W_GROUP_SAFE = {"/whoami", "/help", "/repos", "/repo", "/lang"}

# Từ khoá text thay cho bấm nút (kênh add-on như Google Chat không route click về endpoint).
_W_CONFIRM = {"ok", "confirm", "duyệt", "duyet", "đồng ý", "dong y", "yes", "y", "ừ", "u"}
_W_EDIT = {"sửa", "sua", "chỉnh", "chinh", "edit", "fix"}
_W_CANCEL = {"huỷ", "huy", "hủy", "cancel", "bỏ", "bo", "stop"}
_W_VERIFY_OK = {"đạt", "dat", "ok", "pass", "duyệt", "duyet", "done", "xong", "good"}
_W_REJECT = {"từ chối", "tu choi", "reject", "no", "không", "khong"}
# Gỡ xung đột merge release (chỉ có nghĩa khi bot vừa mời — branch_sync guard `offered`).
_W_FIX_CONFLICT = {"gộp", "gop", "gộp vào", "gop vao", "fix conflict", "resolve",
                   "gỡ xung đột", "go xung dot"}
# Hợp của mọi từ khoá hành động — chặn tin thường (vd "fix bug #123") lọt vào nhánh hành động.
_W_ANY = _W_CONFIRM | _W_EDIT | _W_CANCEL | _W_VERIFY_OK | _W_REJECT | _W_FIX_CONFLICT

# Cho phép nhắm tường minh "ok #12" → tách số request khỏi câu trước khi khớp từ khoá.
_REQ_ID_RE = re.compile(r"#(\d+)")


def _norm_word(text: str) -> str:
    """Chuẩn hoá text → từ khoá: bỏ '#id', emoji/ký hiệu (nhãn nút echo — xem textnorm),
    hạ thường, gộp khoảng trắng."""
    return strip_symbols(_REQ_ID_RE.sub("", text)).lower()


# action → key i18n nhãn nút khi hỏi lại lúc nhập nhằng (nhiều việc cùng khớp 1 từ khoá).
# Resolve t() tại use-site (không phải module-load) để theo đúng ngôn ngữ người dùng.
_ACTION_VERB = {
    "confirm": "disp.verb_confirm", "reject": "disp.verb_reject", "cancel": "disp.verb_cancel",
    "verify_ok": "disp.verb_verify_ok", "mgr_approve": "disp.verb_mgr_approve",
    "mgr_reject": "disp.verb_mgr_reject", "conflict_fix": "disp.verb_conflict_fix",
}
# Mỗi action → 1 từ khoá đại diện (đã có trong _W_*) để _keyword_action map đúng theo status.
_VERB_KW = {
    "confirm": "ok", "mgr_approve": "ok", "verify_ok": "đạt",
    "reject": "sửa", "cancel": "huỷ", "mgr_reject": "reject",
    "conflict_fix": "gộp",
}
# Nhãn nút khử-nhập-nhằng đã chuẩn hoá (mọi ngôn ngữ) → từ khoá. Messenger gửi click dạng TEXT
# (quick-reply ephemeral) ⇒ user echo nguyên nhãn "✅ Allow merge #53"; nếu không nhận diện sẽ
# rơi thành feedback và chạy lại EXECUTING nhầm request khác. Dựng 1 lần từ catalog i18n.
_VERB_LABEL_KW: dict[str, str] = {
    _norm_word(val.replace("#{id}", "")): _VERB_KW[action]
    for action, key in _ACTION_VERB.items()
    for val in TEXTS.get(key, {}).values()
}


def _intent_enabled() -> bool:
    """Lớp 2 (LLM hiểu câu tự nhiên) chỉ bật khi cấu hình cho phép VÀ có OAuth token Claude.
    Không token (vd môi trường test/local) ⇒ tắt ⇒ hành vi giống hệt khi chỉ có từ khoá."""
    s = get_settings()
    return s.intent_llm_enabled and bool(s.claude_code_oauth_token)


def _needs_confirm(intent: Intent, action: str) -> bool:
    """Hành động do LLM suy ra có cần XÁC NHẬN trước không: có, nếu việc KHÔNG hoàn tác (sàn an
    toàn) HOẶC độ chắc chắn dưới ngưỡng cấu hình. Đủ chắc + hoàn tác được → cho làm thẳng."""
    if action in _IRREVERSIBLE:
        return True
    return intent.confidence < get_settings().intent_confidence_threshold


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
        if word in _W_FIX_CONFLICT: return "conflict_fix"
    return None

# Khoá theo user: serialize các event của cùng 1 người (mỗi event là 1 task nền + DB
# session riêng) → tránh đua giữa /start (link) và tin kế tiếp, và tránh tạo request trùng.
_user_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


def _sync_user_language(db: Session, user: User, inbound) -> None:
    """Ngôn ngữ user là STICKY: chốt 1 lần từ TIN CÓ NGHĨA ĐẦU TIÊN họ gửi, lưu User.language,
    về sau luôn dùng giá trị đã lưu — KHÔNG detect lại mỗi tin (tin ngắn "ok"/echo nhãn nút
    tiếng Anh từng làm đổi ngôn ngữ giữa hội thoại). Đổi chủ động bằng lệnh /lang.

    NÚT (callback) và LỆNH (/...) không đại diện ngôn ngữ → không dùng để chốt. Tin đầu
    không đủ tín hiệu (detect None) → fallback language_code client; không có nốt → DEFAULT
    tạm thời, CHƯA persist để tin có nghĩa kế tiếp còn quyết.
    """
    if user.language:
        set_lang(user.language)
        return
    text = inbound.text or ""
    if inbound.callback_data or text.startswith("/"):
        set_lang(inbound.language_code)
        return
    lang = detect(text) or inbound.language_code
    if lang:
        user.language = normalize(lang)
        db.commit()
    set_lang(lang)


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
    # Đặt ngôn ngữ sơ bộ theo client chat (vd Telegram language_code) — đủ cho các tin
    # trước khi biết user (busy/chưa-link/start). Sau khi tra được user sẽ tinh chỉnh lại.
    set_lang(inbound.language_code)
    reply_to = inbound.chat_id or inbound.platform_user_id
    lock = _user_locks[f"{bot_id}:{adapter.name}:{inbound.platform_user_id}"]
    if lock.locked():
        log.info("user %s đang bận — bỏ qua tin mới", inbound.platform_user_id)
        await adapter.send(reply_to, t("disp.busy"))
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
            await adapter.send(reply_to, t("disp.start_dm_only"))
            return
        await _handle_start(db, adapter, inbound.platform_user_id, text, bot_id,
                            language_code=inbound.language_code)
        return

    user = get_user_by_platform(db, adapter.name, inbound.platform_user_id, bot_id)
    if user is None:
        log.warning("chưa liên kết: platform=%r pid=%r text=%r",
                    adapter.name, inbound.platform_user_id, text[:40])
        await adapter.send(reply_to, t("disp.not_linked"))
        return
    # Đã biết user → đặt ngôn ngữ theo hồ sơ user (suy & lưu từ client chat nếu có/đổi).
    _sync_user_language(db, user, inbound)

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
        if inbound.is_group and _cmd0 not in _W_GROUP_SAFE:
            await adapter.send(reply_to, t("disp.admin_dm_only"))
            return
        # Group: lệnh chỉ-đọc trả lời ngay trong thread; DM: như cũ (reply_to = chính user).
        await handle_command(db, adapter, user, text, reply_to=reply_to)
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
        elif req is not None:
            # Nút hiện công khai trong group/space nên người ở workspace KHÁC (bot dùng chung)
            # cũng bấm được. Trước đây bỏ qua IM LẶNG → yêu cầu trông như treo. Báo rõ để họ
            # biết cần người đúng workspace bấm. (req None = callback cũ/đã xoá → im lặng như cũ.)
            set_lang(user.language)
            await adapter.send(reply_to, t("disp.callback_not_yours"))
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
            await adapter.send(reply_to, t("disp.thread_busy", id=active.id))
            return
        if active.status in _TEXT_ACTIVE:          # CLARIFYING → làm rõ; VERIFY → feedback (chủ/manager)
            await orch.handle_message(active, user, text, attachments=inbound.attachments)
        elif active.status == RequestStatus.PLAN_REVIEW:
            await adapter.send(reply_to, t("disp.plan_pending", id=active.id))
        else:                                       # NEW/ANALYZING/EXECUTING
            await adapter.send(reply_to,
                t("disp.req_processing", id=active.id, status=active.status.value))
        return

    # Không còn request mở → tạo request mới (vào dự án đang chọn).
    chosen, repos = _resolve_active_repo(db, user)
    if not repos:
        await adapter.send(reply_to, t("disp.no_repo"))
        return
    if chosen is None:                          # nhiều repo + chưa chọn → bảo chọn
        lines = "\n".join(f"{i}. {r.repo_full_name}" for i, r in enumerate(repos, 1))
        await adapter.send(reply_to, t("disp.pick_repo", lines=lines))
        return
    title = text.splitlines()[0][:200] if text else t("disp.title_image_only")
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


def _pending_requests(db: Session, user: User,
                      *, group_chat_id: str | None = None) -> list[Request]:
    """Mọi việc đang chờ ở cổng duyệt cho user này: request PLAN_REVIEW/VERIFY của chính họ
    (vai requester) + AWAIT_MANAGER của tenant (vai manager) + (manager, trong group) PLAN_REVIEW/
    VERIFY của THREAD này — để manager thao tác thay nhân viên. Dedup, giữ thứ tự (mới nhất trước)."""
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
    return [r for r in reqs if not (r.id in seen or seen.add(r.id))]  # dedup, giữ thứ tự


def _actionable(db: Session, user: User, word: str,
                *, group_chat_id: str | None = None) -> list[tuple[Request, str]]:
    """Lọc các việc đang chờ (`_pending_requests`) còn lại những việc mà từ khoá `word` áp dụng
    được theo status (`_keyword_action`). Trả (request, action)."""
    return [(r, act) for r in _pending_requests(db, user, group_chat_id=group_chat_id)
            if (act := _keyword_action(word, r.status))]


def _recording_run(db: Session, *, tenant_id: int):
    """Bọc run_claude để GHI usage (phase=intent) cho lần phân loại LLM Lớp 2 — classify_intent
    thuần (không biết db/tenant) nên đo lường luồn qua tham số `run` thay vì sửa chữ ký."""
    async def _run(**kw):
        res = await run_claude(**kw)
        usage.record(db, tenant_id=tenant_id, phase="intent", res=res)
        return res
    return _run


async def _try_text_action(db: Session, orch: Orchestrator, user: User, text: str,
                           reply_to: str, inbound=None) -> bool:
    """Map text từ khoá → hành động nút (cho kênh không route click, vd Google Chat add-on).

    Gom mọi việc actionable (requester + manager) rồi quyết: nhắm tường minh `ok #id`; đúng 1
    việc → làm luôn; nhiều việc cùng khớp → hỏi lại bằng nút (mỗi nút mang đúng req.id) thay vì
    đoán. Trả True nếu đã xử lý/đã hỏi. Text không khớp việc nào → False (feedback/làm rõ ở luồng cũ).
    """
    m = _REQ_ID_RE.search(text)
    target_id = int(m.group(1)) if m else None
    # bỏ '#12' + emoji/ký hiệu (nhãn nút) trước khi khớp từ khoá → echo nhãn nút vẫn khớp.
    word = _norm_word(text)
    # Echo nhãn nút khử-nhập-nhằng ("✅ Allow merge #53") → từ khoá tương ứng để route theo id.
    word = _VERB_LABEL_KW.get(word, word)
    group_chat_id = inbound.chat_id if (inbound and inbound.is_group) else None
    intent = None                                      # Lớp 2: Intent(word, confidence) nếu LLM suy ra
    if word not in _W_ANY:                             # Lớp 1 (từ khoá) trượt
        # Lớp 2: nhờ LLM hiểu câu tự nhiên NẾU bật + có việc đang chờ cổng. Bỏ qua khi nhắm
        # '#id' tường minh (câu lạ + id → không đủ chắc) → trả về luồng cũ (feedback/làm rõ).
        if target_id is not None or not _intent_enabled():
            return False
        pending = [r for r in _pending_requests(db, user, group_chat_id=group_chat_id)
                   if r.status in _LLM_GATE_STATUSES]
        if not pending:                                # không ở cổng thuần quyết định → luồng cũ
            return False
        intent = await classify_intent(
            text, [r.status.value for r in pending],
            run=_recording_run(db, tenant_id=user.tenant_id))
        if intent is None:                             # không phải hành động cổng → luồng cũ
            return False
        word = intent.word
    cands = _actionable(db, user, word, group_chat_id=group_chat_id)

    if target_id is not None:                          # nhắm tường minh "ok #12"
        hit = next((c for c in cands if c[0].id == target_id), None)
        if hit is None:
            await orch.adapter.send(
                reply_to, t("disp.req_not_awaiting", id=target_id, word=word))
            return True
        await orch.handle_callback(hit[0], user, cb(hit[1], hit[0].id), reply_to=reply_to)
        return True

    if not cands:                                      # không phải hành động → luồng cũ
        return False
    if len(cands) == 1:                                # rõ ràng (1 việc)
        req, action = cands[0]
        if intent and _needs_confirm(intent, action):  # LLM chưa đủ chắc / việc không hoàn tác → hỏi lại
            buttons = [[Button(t(_ACTION_VERB[action], id=req.id), cb(action, req.id))]]
            await orch.adapter.send(
                reply_to, t("disp.confirm_intent", id=req.id, word=word), buttons)
            return True
        await orch.handle_callback(req, user, cb(action, req.id), reply_to=reply_to)
        return True

    # Nhập nhằng (>1 việc khớp) → hỏi lại; nút mang đúng cb(action, req.id) đi đường callback.
    buttons = [[Button(t(_ACTION_VERB[act], id=r.id), cb(act, r.id))] for r, act in cands]
    await orch.adapter.send(reply_to, t("disp.ambiguous"), buttons)
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
        await orch.adapter.send(reply_to, t("disp.ask_usage"))
        return
    chosen, repos = _resolve_active_repo(db, user)
    if not repos:
        await orch.adapter.send(reply_to, t("disp.no_repo"))
        return
    if chosen is None:
        lines = "\n".join(f"{i}. {r.repo_full_name}" for i, r in enumerate(repos, 1))
        await orch.adapter.send(reply_to, t("disp.ask_pick_repo", lines=lines))
        return
    await orch.adapter.send(reply_to, t("disp.ask_thinking"))
    await orch.ask(chosen, user, question, reply_to=reply_to)


async def _handle_start(db: Session, adapter: ChannelAdapter, platform_user_id: str, text: str,
                        bot_id: int | None = None, *, language_code: str | None = None) -> None:
    parts = text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await adapter.send(platform_user_id, t("disp.start_welcome"))
        return
    try:
        user = link_user(db, parts[1].strip(), platform_user_id, platform=adapter.name, bot_id=bot_id)
    except AlreadyLinkedError:
        # Tài khoản này đã thuộc 1 tenant khác trên cùng bot → không link chồng (route nhập nhằng).
        await adapter.send(platform_user_id, t("disp.start_already_linked"))
        return
    if user is None:
        await adapter.send(platform_user_id, t("disp.start_bad_token"))
        return
    # KHÔNG persist language_code lúc link: ngôn ngữ chốt từ TIN ĐẦU TIÊN user gửi
    # (_sync_user_language) — ghi sẵn ở đây thì detection không bao giờ chạy.
    if language_code:
        set_lang(language_code)             # chỉ cho tin chào ngay dưới
    try:
        db.commit()
    except IntegrityError:
        # (platform, platform_user_id) đã tồn tại → tài khoản này đã liên kết bằng token khác.
        db.rollback()
        await adapter.send(platform_user_id, t("disp.start_already_linked"))
        return
    await adapter.send(platform_user_id,
                       t("disp.start_linked", role=user.role.value, help=help_text()))


# Alias tương thích ngược: tên cũ thời chỉ-Telegram (tests/poller/main vẫn dùng được).
handle_telegram_update = handle_channel_update
