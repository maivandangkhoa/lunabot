"""Settings — đọc từ env (.env local hoặc env_file trên VM).

Mọi cấu hình tập trung ở đây. Không đọc os.environ rải rác trong code.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- App ---
    luna_env: str = "development"
    log_level: str = "INFO"
    secret_key: str = "change-me"

    # --- Database ---
    database_url: str = "postgresql+psycopg://luna:luna@localhost:5432/luna"

    # --- Claude Code CLI (M1) ---
    claude_code_oauth_token: str | None = None
    claude_timeout_s: int = 1800

    # --- GitHub App (M2) ---
    github_app_id: str | None = None
    github_app_private_key_path: Path | None = None
    github_app_webhook_secret: str | None = None

    # --- Telegram (M3) ---
    telegram_bot_token: str | None = None
    telegram_webhook_secret: str | None = None
    # "webhook" (FastAPI endpoint) hoặc "polling" (tự getUpdates — hợp VM khoá port).
    telegram_mode: str = "webhook"
    # Username bot (không @) — để nhận diện @mention trong group ở mode webhook (poller tự lấy
    # qua getMe). Đặt khi muốn dùng group + webhook.
    telegram_bot_username: str | None = None

    # --- Google Chat (G) ---
    google_chat_enabled: bool = False
    # Service account JSON: đường dẫn file hoặc chuỗi JSON inline (secret, KHÔNG log).
    google_chat_sa_json: str | None = None
    # Project number của bot — dùng kiểm tra email SA phát hành token (gsuiteaddons).
    google_chat_project_number: str | None = None
    # Audience JWT inbound = đúng URL webhook (Workspace add-on gửi OIDC token aud=URL).
    # Set giá trị này để BẬT verify; để trống = bỏ verify (dev).
    google_chat_audience: str | None = None
    # True = từ chối 401 khi JWT sai; False = audit (log nhưng cho qua) để debug.
    google_chat_verify_enforce: bool = True

    # --- Workspace ---
    workspace: Path = Field(default=Path("/workspace"))

    # --- Git identity ---
    git_author_name: str = "luna bot"
    git_author_email: str = "bot@luna.dev"

    @property
    def is_production(self) -> bool:
        return self.luna_env.lower() in {"production", "prod"}


@lru_cache
def get_settings() -> Settings:
    """Cache 1 instance cho toàn app. Override env trong test bằng env vars."""
    return Settings()
