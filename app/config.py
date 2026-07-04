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

    # --- Lớp 2: hiểu câu tự nhiên cho hành động cổng (xem app/intent.py) ---
    # Khi từ khoá cứng (ok/sửa/huỷ…) KHÔNG khớp nhưng user đang có việc chờ duyệt, nhờ Claude
    # chuẩn hoá câu của họ về 1 từ khoá canonical rồi LUÔN xin xác nhận. Tắt = chỉ dùng từ khoá.
    intent_llm_enabled: bool = True
    intent_timeout_s: int = 25            # phân loại ngắn → timeout nhỏ (không phải tác vụ nặng)
    # LLM tự chấm độ chắc chắn (0..1): >= ngưỡng → làm luôn; dưới → xin xác nhận. Hành động
    # KHÔNG hoàn tác (merge production) thì LUÔN xác nhận bất kể điểm (xem dispatcher._IRREVERSIBLE).
    intent_confidence_threshold: float = 0.75

    # --- Usage metering / quota subscription ---
    # Trần QUY ĐỔI USD của account Claude subscription theo cửa sổ trượt 5h / 7 ngày —
    # KHÔNG có API công khai để hỏi, calibrate thực nghiệm: tổng cost_usd tích luỹ tới lúc
    # đụng trần (usage_records.status="limit") ≈ trần. Để trống = chưa biết (trang admin
    # chỉ hiện số đã dùng, không hiện %).
    sub_quota_usd_5h: float | None = None
    sub_quota_usd_week: float | None = None

    # --- Deploy verify (sau merge dev) ---
    # Bật: sau khi merge vào dev, chờ GitHub Action build+deploy xong + curl URL dev (200)
    # rồi mới mời manager. Tắt = giữ hành vi cũ (merge xong mời manager ngay).
    dev_verify_enabled: bool = True
    deploy_poll_interval_s: int = 15      # nhịp poll Actions run
    deploy_timeout_s: int = 900           # tối đa chờ 1 lần deploy (15 phút)
    # Bật mặc định cho mọi repo: nếu sau ngần này giây KHÔNG thấy workflow run nào cho commit
    # merge → coi như repo không có CI deploy → bỏ qua cổng, mời manager ngay (không auto-fix nhầm).
    deploy_ci_grace_s: int = 90
    # Số vòng auto-fix tối đa khi deploy/curl lỗi (0 = không auto-fix, chỉ báo lỗi).
    dev_verify_max_rounds: int = 2

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

    # --- Zalo OA (shared instance — cấu hình bằng env, không qua wizard) ---
    zalo_enabled: bool = False
    zalo_app_id: str | None = None
    zalo_app_secret: str | None = None
    zalo_oa_access_token: str | None = None
    zalo_oa_refresh_token: str | None = None
    zalo_oa_id: str | None = None
    # True = từ chối 403 khi signature sai; False = audit (log) để debug.
    zalo_verify_enforce: bool = True

    # --- Facebook Messenger (shared instance — cấu hình bằng env, không qua wizard) ---
    messenger_enabled: bool = False
    messenger_app_secret: str | None = None
    messenger_page_access_token: str | None = None
    messenger_verify_token: str | None = None       # token tự đặt, khớp lúc đăng ký webhook (GET)
    messenger_page_id: str | None = None
    # True = từ chối 403 khi signature sai; False = audit (log) để debug.
    messenger_verify_enforce: bool = True

    # --- Web wizard self-service (GitHub OAuth + provisioning) ---
    # Bật web wizard khi đủ các biến này. URL công khai để dựng OAuth callback + webhook đa bot.
    public_base_url: str | None = None
    # OAuth user-to-server của GitHub App (Settings → tab "OAuth credentials").
    github_oauth_client_id: str | None = None
    github_oauth_client_secret: str | None = None
    # Slug của GitHub App (trong URL https://github.com/apps/<slug>) — dựng nút "Cấp quyền repo".
    github_app_slug: str | None = None
    # Khoá ký cookie phiên web (itsdangerous-style). Đặt giá trị ngẫu nhiên bền vững.
    web_session_secret: str = "change-me-web"
    # Fernet key (urlsafe base64 32-byte) mã hoá token bot BYO khi lưu DB. Sinh bằng
    # `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
    bot_token_enc_key: str | None = None
    # Bật tuỳ chọn "container riêng" trong wizard (cần mount Docker socket — rủi ro bảo mật).
    dedicated_container_enabled: bool = False
    # CHỈ DEV: cho phép /dev/login bỏ qua GitHub OAuth (repo giả) để xem/thử wizard cục bộ.
    # MẶC ĐỊNH False — TUYỆT ĐỐI không bật ở production.
    web_dev_login: bool = False

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
