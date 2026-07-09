"""Provisioning self-service — biến lựa chọn trong web wizard thành 1 bot Luna dùng được ngay.

`provision()` tạo Tenant + Repository + User(admin/manager, kiêm cổng duyệt) + Bot, rồi:
- bot=shared  → dùng bot Luna CHUNG (chỉ cấp /start <token>; user.bot_id=NULL).
- bot=own     → validate token BotFather (getMe), mã hoá lưu, setWebhook /webhook/telegram/{id}.
- host=dedicated → (tier 2) spawn container riêng nếu được bật.

Trả về dict hướng dẫn onboarding (deeplink Telegram + link_token). Mọi side-effect chat
(getMe/setWebhook) inject qua `adapter_factory` để test monkeypatch — theo style orchestrator.
"""
from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from typing import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.channels.telegram import TelegramAdapter
from app.models import Bot, UserRole
from app.onboarding import add_repository, create_tenant, create_user
from app.token_crypto import encrypt_token

log = logging.getLogger("luna.provisioning")

AdapterFactory = Callable[[str], TelegramAdapter]


class ProvisioningError(RuntimeError):
    """Lỗi provisioning rõ ràng để web layer hiển thị cho người dùng."""


@dataclass
class ProvisionResult:
    tenant_id: int
    repo_id: int
    bot_id: int
    user_id: int
    link_token: str
    bot_username: str | None
    deeplink: str
    mode: str
    platform: str = "telegram"


def _default_factory(token: str) -> TelegramAdapter:
    return TelegramAdapter(token=token)


async def provision(
    db: Session,
    settings,
    *,
    owner_github_id: int,
    owner_github_login: str,
    owner_name: str,
    repo_full_name: str,
    installation_id: int,
    bot_choice: str,                 # "shared" | "own"
    hosting_choice: str,             # "shared_instance" | "dedicated_container"
    platform: str = "telegram",      # "telegram" | "google_chat"
    display_name: str | None = None,
    bot_token: str | None = None,    # bắt buộc khi bot_choice="own"
    base_branch: str = "dev",
    prod_branch: str = "main",
    adapter_factory: AdapterFactory | None = None,
) -> ProvisionResult:
    factory = adapter_factory or _default_factory
    name = display_name or repo_full_name.split("/")[-1]

    # Google Chat / Zalo / Messenger / Slack = kênh DÙNG CHUNG toàn cục (1 add-on / 1 OA / 1 Page
    # / 1 Slack App cho mọi tenant, cấu hình bằng env — không token/webhook riêng từng tenant như
    # Telegram) ⇒ chỉ hỗ trợ bot chung. Ép shared, chặn "own".
    if platform in ("google_chat", "zalo", "messenger", "slack"):
        if bot_choice == "own":
            raise ProvisioningError(
                f"{platform} chỉ hỗ trợ bot Luna chung — chưa có bot riêng cho kênh này.")
        bot_choice = "shared"

    # 0) Bot riêng: validate token + CHẶN TRÙNG trước khi tạo gì (1 token Telegram chỉ 1
    #    webhook → tạo trùng sẽ ghi đè webhook nhau + loạn link). Lỗi ⇒ chưa tạo tenant/repo.
    own_username: str | None = None
    if bot_choice == "own":
        if not bot_token:
            raise ProvisioningError("Bot riêng cần token từ BotFather.")
        if not settings.public_base_url:
            raise ProvisioningError("Thiếu PUBLIC_BASE_URL — không dựng được webhook cho bot riêng.")
        own_username = await _validate_own_token(bot_token, factory)
        dup = db.scalar(select(Bot).where(
            Bot.platform == "telegram", Bot.mode == "own", Bot.username == own_username))
        if dup is not None:
            raise ProvisioningError(
                f"Bot @{own_username} đã được đăng ký rồi. Dùng lại deeplink cũ, hoặc tạo bot "
                "MỚI trong @BotFather (token khác) rồi thử lại.")

    # 1) Tenant + Repository + chủ sở hữu.
    tenant = create_tenant(db, name=name)
    tenant.owner_github_id = owner_github_id
    tenant.owner_github_login = owner_github_login
    repo = add_repository(db, tenant, repo_full_name, installation_id,
                          base_branch=base_branch, prod_branch=prod_branch)

    # 2) Bot row. Container riêng chỉ áp dụng cho Telegram (GC là add-on dùng chung).
    dep_mode = ("dedicated_container"
                if (platform == "telegram"
                    and hosting_choice == "dedicated_container"
                    and settings.dedicated_container_enabled)
                else "shared_instance")
    bot = Bot(
        tenant_id=tenant.id, platform=platform, mode=bot_choice,
        deployment_mode=dep_mode, display_name=name,
        status="provisioning" if dep_mode == "dedicated_container" else "active",
    )
    db.add(bot)
    db.flush()

    # 3) Telegram bot riêng: mã hoá token + setWebhook (username đã validate ở bước 0).
    #    Google Chat / Telegram chung: không có username/deeplink riêng (link thủ công /start).
    bot_username: str | None = (
        settings.telegram_bot_username if platform == "telegram" else None)
    if bot_choice == "own":
        bot_username = await _setup_own_bot(bot, bot_token, own_username, settings, factory)

    # 4) User chủ (admin = kiêm manager, tự duyệt merge main). Bot riêng ⇒ user.bot_id = bot.id.
    user = create_user(db, tenant, role=UserRole.ADMIN, display_name=owner_name,
                       platform=platform, bot_id=(bot.id if bot_choice == "own" else None))
    user.active_repo_id = repo.id

    db.commit()

    # 5) (tier 2) container riêng — sau commit để có id; lỗi không rollback tenant đã tạo.
    if dep_mode == "dedicated_container":
        _try_spawn_container(db, bot, tenant, repo, settings)

    deeplink = (f"https://t.me/{bot_username}?start={user.link_token}"
                if bot_username else f"/start {user.link_token}")
    return ProvisionResult(
        tenant_id=tenant.id, repo_id=repo.id, bot_id=bot.id, user_id=user.id,
        link_token=user.link_token, bot_username=bot_username, deeplink=deeplink,
        mode=bot_choice, platform=platform,
    )


async def _validate_own_token(token: str, factory: AdapterFactory) -> str:
    """getMe → trả username. Raise nếu token sai (chưa tạo gì nên rollback sạch)."""
    adapter = factory(token)
    try:
        me = await adapter.get_me()
        if not me or not me.get("username"):
            raise ProvisioningError("Token bot không hợp lệ (getMe thất bại). Kiểm tra lại BotFather.")
        return me["username"]
    finally:
        await adapter.aclose()


async def _setup_own_bot(bot: Bot, token: str, username: str, settings,
                         factory: AdapterFactory) -> str:
    """Gắn username (đã validate) → mã hoá token → setWebhook /webhook/telegram/{id}. Trả username."""
    bot.username = username
    bot.token_encrypted = encrypt_token(token, settings.bot_token_enc_key)
    bot.webhook_secret = secrets.token_urlsafe(24)
    adapter = factory(token)
    try:
        from app.bot_registry import register_webhook
        await register_webhook(bot, adapter, settings)
        return username
    finally:
        await adapter.aclose()


def _try_spawn_container(db: Session, bot: Bot, tenant, repo, settings) -> None:
    """Tier 2: spawn container riêng. Lỗi → đánh dấu bot.status=error (không chặn tenant)."""
    try:
        from app.container_provisioner import provision_container
        bot.container_name = provision_container(bot, tenant, repo, settings)
        bot.status = "active"
    except Exception as exc:  # noqa: BLE001
        log.exception("spawn container cho bot #%s lỗi", bot.id)
        bot.status = "error"
    db.commit()
