"""FastAPI app — webhooks (Telegram/GitHub) + health.

Telegram webhook: verify secret header → dispatcher → orchestrator (FSM).
GitHub webhook: stub (M2 dùng REST chủ động; webhook events để gắn CI/sync sau).
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, Request, Response, status
from fastapi.responses import JSONResponse

from app.channels.google_chat import GoogleChatAdapter, verify_google_jwt
from app.channels.telegram import TelegramAdapter
from app.config import get_settings
from app.db import SessionLocal
from app.dispatcher import handle_channel_update
from app.github_app import GitHubApp
from app.poller import run_polling

settings = get_settings()
logging.basicConfig(level=settings.log_level)
log = logging.getLogger("luna")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Bật long-polling khi TELEGRAM_MODE=polling; tắt gọn khi shutdown."""
    task = None
    stop = asyncio.Event()
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
        if x_telegram_bot_api_secret_token != settings.telegram_webhook_secret:
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
    # Trả JSON rỗng hợp lệ: add-on coi là "đã xử lý, không kèm message" (tránh
    # "App not responding"). Reply thật gửi bất đồng bộ qua REST.
    return JSONResponse(content={}, status_code=status.HTTP_200_OK)


@app.post("/webhook/github")
async def webhook_github() -> Response:
    """GitHub App webhook (sync installation / CI sau). M2 thao tác git qua REST chủ động."""
    log.info("github webhook received (stub)")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
