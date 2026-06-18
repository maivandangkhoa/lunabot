"""Tier 2: container riêng cho mỗi tenant — cô lập thật (tuỳ chọn, mặc định TẮT).

Một container = bản sao luna ĐƠN-BOT (như deploy gốc) phục vụ đúng 1 tenant: chạy polling
với token bot của tenant, có DATABASE_URL/WORKSPACE riêng. Vì đơn-bot nên KHÔNG cần route đa
bot bên trong — tái dùng nguyên code path cũ.

⚠️ Cần mount Docker socket vào container luna gốc → bề mặt tấn công lớn. Chỉ bật
`DEDICATED_CONTAINER_ENABLED=true` cho tenant trả phí, có chủ đích. subprocess inject được
để test.
"""
from __future__ import annotations

import logging
import subprocess

from app.models import Bot
from app.token_crypto import decrypt_token

log = logging.getLogger("luna.container")

_IMAGE = "luna:latest"


def _container_name(bot: Bot) -> str:
    return f"luna-tenant-{bot.tenant_id}"


def provision_container(bot: Bot, tenant, repo, settings, *, runner=subprocess.run) -> str:
    """`docker run -d` 1 container đơn-bot cho tenant. Trả tên container.

    Env tenant-riêng: token bot (giải mã), DATABASE_URL riêng (theo quy ước
    <base>_tenant_<id>), WORKSPACE riêng. GitHub App + Claude config kế thừa từ env_file gốc.
    """
    name = _container_name(bot)
    token = decrypt_token(bot.token_encrypted, settings.bot_token_enc_key) if bot.token_encrypted else ""
    # DB riêng cho tenant (ops phải tạo trước hoặc trỏ Postgres tự tạo) — cô lập dữ liệu.
    db_url = f"{settings.database_url.rsplit('/', 1)[0]}/luna_tenant_{bot.tenant_id}"
    cmd = [
        "docker", "run", "-d", "--name", name, "--restart", "unless-stopped",
        "--env-file", "/etc/luna/luna.env",          # GitHub App + Claude token chung
        "-e", "TELEGRAM_MODE=polling",
        "-e", f"TELEGRAM_BOT_TOKEN={token}",
        "-e", f"TELEGRAM_BOT_USERNAME={bot.username or ''}",
        "-e", f"DATABASE_URL={db_url}",
        "-e", f"WORKSPACE=/workspace/tenant-{bot.tenant_id}",
        "--memory", "2g", "--cpus", "1.5",
        _IMAGE,
    ]
    log.info("spawn container %s cho tenant #%s (KHÔNG log token)", name, bot.tenant_id)
    runner(cmd, check=True, capture_output=True)
    return name


def teardown_container(bot: Bot, *, runner=subprocess.run) -> None:
    """Xoá container của tenant (khi xoá bot)."""
    runner(["docker", "rm", "-f", _container_name(bot)], check=False, capture_output=True)
