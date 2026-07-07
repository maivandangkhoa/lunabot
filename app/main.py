"""FastAPI app — webhooks (Telegram/GitHub) + health.

Telegram webhook: verify secret header → dispatcher → orchestrator (FSM).
GitHub webhook: stub (M2 dùng REST chủ động; webhook events để gắn CI/sync sau).
"""
from __future__ import annotations

import asyncio
import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, Query, Request, Response, status
from fastapi.responses import JSONResponse, PlainTextResponse

from app import bot_registry
from app.channels.google_chat import (
    GoogleChatAdapter,
    ack_update_message,
    is_button_click,
    verify_google_jwt,
)
from app.channels.messenger import MessengerAdapter
from app.channels.messenger import merge_events as merge_messenger_events
from app.channels.zalo import ZaloAdapter
from app.channels.telegram import TelegramAdapter
from app.config import get_settings
from app.db import SessionLocal
from app.dispatcher import handle_channel_update
from app.github_app import GitHubApp
from app.poller import run_polling
from app.recovery import recover_interrupted_requests, rekick_pending_deploys
from app.web.activity import router as web_activity_router
from app.web.admin import router as web_admin_router
from app.web.approvals import router as web_approvals_router
from app.web.routes import router as web_router
from app.web.team import router as web_team_router
from app.web.usage import router as web_usage_router

settings = get_settings()
logging.basicConfig(level=settings.log_level)
log = logging.getLogger("luna")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Bật long-polling khi TELEGRAM_MODE=polling; tắt gọn khi shutdown."""
    task = None
    stop = asyncio.Event()
    try:
        n = await recover_interrupted_requests(settings)
        if n:
            log.warning("recovery: đã đóng %d request kẹt do restart", n)
        m = await rekick_pending_deploys(settings)
        if m:
            log.info("recovery: tiếp tục kiểm thử deploy cho %d request ở MERGED_DEV", m)
    except Exception:  # noqa: BLE001 — recovery không được làm hỏng startup
        log.exception("recovery khởi động lỗi")
    if settings.telegram_mode == "polling" and settings.telegram_bot_token:
        task = asyncio.create_task(run_polling(stop))
        log.info("Khởi động Telegram poller")
    try:
        yield
    finally:
        if task is not None:
            stop.set()
            await task


app = FastAPI(title="luna", version="0.0.0", lifespan=lifespan)
app.include_router(web_router)  # web wizard self-service (/, /login, /wizard, /dashboard…)
app.include_router(web_team_router)  # quản lý người dùng + workspace (/users, /tenants/rename)
app.include_router(web_approvals_router)  # duyệt/từ chối merge production qua web (/requests/{id}/…)
app.include_router(web_activity_router)  # dòng sự kiện + bộ lọc & xoá log (/activity, /activity/clear)
app.include_router(web_admin_router)  # super admin nền tảng — xem mọi tenant (/admin)
app.include_router(web_usage_router)  # đo lượng dùng Claude per-tenant (/usage, /admin/usage)


_CSP = (
    "default-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "img-src 'self' data:; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "script-src 'self' 'unsafe-inline'"
)


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    """Defense-in-depth cho các trang HTML render tay: chống clickjacking + backstop XSS."""
    resp = await call_next(request)
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    resp.headers.setdefault("Content-Security-Policy", _CSP)
    return resp


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "env": settings.luna_env}


@app.post("/webhook/telegram")
async def webhook_telegram(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> Response:
    """Telegram webhook. Trả 200 cả khi lỗi nội bộ để Telegram không retry bão."""
    if settings.telegram_webhook_secret:
        if not hmac.compare_digest(x_telegram_bot_api_secret_token or "",
                                   settings.telegram_webhook_secret):
            return Response(status_code=status.HTTP_403_FORBIDDEN)

    raw = await request.json()
    db = SessionLocal()
    try:
        adapter = TelegramAdapter(token=settings.telegram_bot_token or "",
                                  bot_username=settings.telegram_bot_username)
        github = GitHubApp.from_settings()
        await handle_channel_update(db, adapter, github, raw)
        await adapter.aclose()
        await github.aclose()
    except Exception:  # noqa: BLE001 — webhook không được để lỗi rò ra Telegram
        log.exception("telegram webhook xử lý lỗi")
    finally:
        db.close()
    return Response(status_code=status.HTTP_200_OK)


@app.post("/webhook/telegram/{bot_id}")
async def webhook_telegram_bot(
    bot_id: int,
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> Response:
    """Webhook bot RIÊNG (provision qua web wizard). Route theo bot_id → adapter+tenant đúng.

    Trả 200 cả khi lỗi (Telegram không retry bão). Verify secret theo từng bot.
    """
    db = SessionLocal()
    try:
        bot = bot_registry.get_bot(db, bot_id)
        if bot is None or bot.platform != "telegram" or bot.mode != "own":
            return Response(status_code=status.HTTP_404_NOT_FOUND)
        if bot.webhook_secret and not hmac.compare_digest(
                x_telegram_bot_api_secret_token or "", bot.webhook_secret):
            return Response(status_code=status.HTTP_403_FORBIDDEN)
        raw = await request.json()
        adapter = bot_registry.build_adapter(bot)
        try:
            github = GitHubApp.from_settings()
        except Exception:  # noqa: BLE001 — GitHub chưa cấu hình ⇒ EXECUTING sẽ báo lỗi rõ
            github = None
        try:
            await handle_channel_update(db, adapter, github, raw, bot_id=bot.id)
        finally:
            await adapter.aclose()
            if github is not None:
                await github.aclose()
    except Exception:  # noqa: BLE001 — webhook không để lỗi rò ra Telegram
        log.exception("telegram bot=%s webhook xử lý lỗi", bot_id)
    finally:
        db.close()
    return Response(status_code=status.HTTP_200_OK)


_bg_tasks: set[asyncio.Task] = set()  # giữ ref tránh GC nuốt task nền


async def _process_google_chat(raw: dict) -> None:
    """Chạy nền 1 event Chat: Claude lâu nên KHÔNG block response webhook.

    Adapter gửi lại qua REST async (service account) nên reply vẫn tới space.
    """
    db = SessionLocal()
    adapter = GoogleChatAdapter.from_settings(settings)
    try:
        github = GitHubApp.from_settings()
    except Exception:  # noqa: BLE001 — GitHub chưa cấu hình ⇒ EXECUTING sẽ báo lỗi rõ
        github = None
    try:
        await handle_channel_update(db, adapter, github, raw)
    except Exception:  # noqa: BLE001
        log.exception("google_chat xử lý lỗi")
    finally:
        await adapter.aclose()
        if github is not None:
            await github.aclose()
        db.close()


@app.post("/webhook/google_chat")
async def webhook_google_chat(
    request: Request,
    authorization: str | None = Header(default=None),
) -> Response:
    """Google Chat webhook. Ack 200 ngay (Chat timeout ~30s), xử lý nền."""
    if not settings.google_chat_enabled:
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    if settings.google_chat_audience:
        token = (authorization or "").removeprefix("Bearer ").strip()
        expected_email = (
            f"service-{settings.google_chat_project_number}"
            "@gcp-sa-gsuiteaddons.iam.gserviceaccount.com"
            if settings.google_chat_project_number else None
        )
        try:
            await verify_google_jwt(token, settings.google_chat_audience,
                                    expected_email=expected_email)
            log.info("google_chat JWT verify OK")
        except Exception as exc:  # noqa: BLE001
            log.warning("google_chat: JWT inbound không hợp lệ: %r", exc)
            if settings.google_chat_verify_enforce:
                return Response(status_code=status.HTTP_401_UNAUTHORIZED)

    raw = await request.json()
    task = asyncio.create_task(_process_google_chat(raw))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    # Bấm nút = 'action' đồng bộ: phải trả action hợp lệ, không thì Chat báo
    # "unable to process". Cập nhật message bỏ nút + báo đang xử lý; kết quả thật
    # gửi async qua REST. Tin nhắn thường thì {} rỗng là đủ.
    if is_button_click(raw):
        return JSONResponse(
            content=ack_update_message("⏳ Đã nhận, đang xử lý…"),
            status_code=status.HTTP_200_OK,
        )
    return JSONResponse(content={}, status_code=status.HTTP_200_OK)


async def _process_zalo(raw: dict, bot_id: int | None = None) -> None:
    """Xử lý nền 1 event Zalo (Claude lâu nên KHÔNG block response webhook)."""
    db = SessionLocal()
    if bot_id is not None:
        bot = bot_registry.get_bot(db, bot_id)
        if bot is None or bot.platform != "zalo":
            db.close()
            return
        adapter = bot_registry.build_adapter(bot)
    else:
        adapter = ZaloAdapter.from_settings(settings)
    try:
        github = GitHubApp.from_settings()
    except Exception:  # noqa: BLE001
        github = None
    try:
        await handle_channel_update(db, adapter, github, raw,
                                    bot_id=bot_id)
    except Exception:  # noqa: BLE001
        log.exception("zalo xử lý lỗi")
    finally:
        await adapter.aclose()
        if github is not None:
            await github.aclose()
        db.close()


@app.get("/webhook/zalo")
async def webhook_zalo_verify(challenge: str | None = None) -> Response:
    """Zalo OA webhook registration: GET với ?challenge=<token> → trả {"challenge": token}."""
    if not settings.zalo_enabled:
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    if challenge:
        from fastapi.responses import JSONResponse as _J
        return _J(content={"challenge": challenge})
    return Response(status_code=status.HTTP_200_OK)


@app.post("/webhook/zalo")
async def webhook_zalo(
    request: Request,
    x_zoa_signature: str | None = Header(default=None),
) -> Response:
    """Zalo OA shared webhook. Ack 200 ngay, xử lý nền."""
    if not settings.zalo_enabled:
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    body = await request.body()
    # Enforce khi có secret: thiếu HEADER cũng bị chặn (không fail-open). Chỉ audit-mode
    # (zalo_verify_enforce=False) mới cho qua để debug.
    if settings.zalo_app_secret and settings.zalo_verify_enforce:
        adapter_tmp = ZaloAdapter.from_settings(settings)
        if not x_zoa_signature or not adapter_tmp.verify_signature(body, x_zoa_signature):
            log.warning("zalo: signature thiếu/không hợp lệ")
            return Response(status_code=status.HTTP_403_FORBIDDEN)
    import json as _json
    try:
        raw = _json.loads(body)
    except Exception:  # noqa: BLE001
        return Response(status_code=status.HTTP_400_BAD_REQUEST)
    task = asyncio.create_task(_process_zalo(raw))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return Response(status_code=status.HTTP_200_OK)


@app.get("/webhook/zalo/{bot_id}")
async def webhook_zalo_bot_verify(bot_id: int, challenge: str | None = None) -> Response:
    """Webhook registration cho Zalo bot riêng (own mode)."""
    if challenge:
        from fastapi.responses import JSONResponse as _J
        return _J(content={"challenge": challenge})
    return Response(status_code=status.HTTP_200_OK)


@app.post("/webhook/zalo/{bot_id}")
async def webhook_zalo_bot(
    bot_id: int,
    request: Request,
    x_zoa_signature: str | None = Header(default=None),
) -> Response:
    """Webhook Zalo bot riêng. Ack 200 ngay, xử lý nền."""
    db = SessionLocal()
    try:
        bot = bot_registry.get_bot(db, bot_id)
        if bot is None or bot.platform != "zalo" or bot.mode != "own":
            return Response(status_code=status.HTTP_404_NOT_FOUND)
        body = await request.body()
        if bot.webhook_secret:
            from app.token_crypto import decrypt_token
            app_secret = decrypt_token(bot.webhook_secret, settings.bot_token_enc_key)
            tmp = ZaloAdapter(app_id="", app_secret=app_secret, access_token="")
            if not x_zoa_signature or not tmp.verify_signature(body, x_zoa_signature):
                log.warning("zalo bot=%s: signature thiếu/không hợp lệ", bot_id)
                return Response(status_code=status.HTTP_403_FORBIDDEN)
        import json as _json
        try:
            raw = _json.loads(body)
        except Exception:  # noqa: BLE001
            return Response(status_code=status.HTTP_400_BAD_REQUEST)
        task = asyncio.create_task(_process_zalo(raw, bot_id=bot_id))
        _bg_tasks.add(task)
        task.add_done_callback(_bg_tasks.discard)
    except Exception:  # noqa: BLE001
        log.exception("zalo bot=%s webhook lỗi", bot_id)
    finally:
        db.close()
    return Response(status_code=status.HTTP_200_OK)


async def _process_messenger(raw: dict) -> None:
    """Xử lý nền 1 'messaging' event Messenger (Claude lâu nên KHÔNG block webhook)."""
    db = SessionLocal()
    adapter = MessengerAdapter.from_settings(settings)
    try:
        github = GitHubApp.from_settings()
    except Exception:  # noqa: BLE001
        github = None
    try:
        await handle_channel_update(db, adapter, github, raw)
    except Exception:  # noqa: BLE001
        log.exception("messenger xử lý lỗi")
    finally:
        await adapter.aclose()
        if github is not None:
            await github.aclose()
        db.close()


@app.get("/webhook/messenger")
async def webhook_messenger_verify(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
) -> Response:
    """Messenger webhook registration: GET hub.challenge → trả challenge thô khi verify_token khớp."""
    if not settings.messenger_enabled:
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    if (hub_mode == "subscribe" and settings.messenger_verify_token
            and hmac.compare_digest(hub_verify_token or "", settings.messenger_verify_token)):
        return PlainTextResponse(hub_challenge or "")
    return Response(status_code=status.HTTP_403_FORBIDDEN)


@app.post("/webhook/messenger")
async def webhook_messenger(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
) -> Response:
    """Messenger webhook. Ack 200 ngay; 1 POST gộp nhiều event → tách entry[].messaging[]."""
    if not settings.messenger_enabled:
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    body = await request.body()
    # Enforce khi có secret: thiếu HEADER cũng bị chặn (không fail-open). Chỉ audit-mode
    # (messenger_verify_enforce=False) mới cho qua để debug.
    if settings.messenger_app_secret and settings.messenger_verify_enforce:
        tmp = MessengerAdapter.from_settings(settings)
        if not x_hub_signature_256 or not tmp.verify_signature(body, x_hub_signature_256):
            log.warning("messenger: signature thiếu/không hợp lệ")
            return Response(status_code=status.HTTP_403_FORBIDDEN)
    import json as _json
    try:
        data = _json.loads(body)
    except Exception:  # noqa: BLE001
        return Response(status_code=status.HTTP_400_BAD_REQUEST)
    for entry in data.get("entry", []):
        # Gộp ảnh + chữ user gửi một lượt (Messenger tách event nhưng chung 1 POST).
        for ev in merge_messenger_events(entry.get("messaging", [])):
            task = asyncio.create_task(_process_messenger(ev))
            _bg_tasks.add(task)
            task.add_done_callback(_bg_tasks.discard)
    return Response(status_code=status.HTTP_200_OK)


@app.post("/webhook/github")
async def webhook_github() -> Response:
    """GitHub App webhook (sync installation / CI sau). M2 thao tác git qua REST chủ động."""
    log.info("github webhook received (stub)")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
