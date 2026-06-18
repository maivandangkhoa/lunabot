# Self-service onboarding — web wizard tạo bot Luna cho repo của khách

Cho phép người dùng tự tạo một bot Luna bảo trì repo của họ qua web: **đăng nhập GitHub →
cấp quyền repo → chọn bot → dùng ngay** (qua Telegram). Không cần admin thao tác tay.

> Mã: `app/web/` (wizard), `app/github_oauth.py`, `app/provisioning.py`, `app/bot_registry.py`,
> `app/container_provisioner.py`. Endpoint webhook đa bot: `POST /webhook/telegram/{bot_id}`.

## Kiến trúc 30 giây

```
/  → /login (GitHub OAuth) → /oauth/github/callback → /wizard
     ↳ "Cấp quyền repo" = cài GitHub App (chọn repo) → /setup → /wizard (repo hiện ra)
/wizard → POST /wizard/create → provision() → /done (deeplink /start <token>)
```

`provision()` tạo **Tenant + Repository + User(admin=manager) + Bot**. Hai lựa chọn người dùng tự chọn:

| Lựa chọn | shared (mặc định) | own |
|---|---|---|
| **Bot** | dùng bot Luna chung `@<TELEGRAM_BOT_USERNAME>` | bot riêng (BotFather token) → `setWebhook /webhook/telegram/{bot_id}` |
| **Hạ tầng** | chạy chung 1 process luna (route đa bot) | container riêng/tenant (tier 2, cần bật) |

Cô lập tenant: user lookup scope theo `(bot_id, platform, platform_user_id)` → cùng 1 tài khoản
Telegram nói với nhiều bot khác tenant không lẫn. Token bot riêng **mã hoá Fernet** trước khi lưu DB.

## Bước 1 — Cấu hình GitHub App cho OAuth + install

Trong GitHub App đang dùng (Settings → Developer settings → GitHub Apps):
1. **Callback URL**: `https://<PUBLIC_BASE_URL>/oauth/github/callback`.
2. **Setup URL** (sau khi cài App): `https://<PUBLIC_BASE_URL>/setup` (bật "Redirect on update").
3. Lấy **Client ID** + tạo **Client secret** (mục "OAuth credentials") → đặt vào env.
4. Ghi lại **slug** trong URL `https://github.com/apps/<slug>` → `GITHUB_APP_SLUG`.
5. Quyền tối thiểu: `Contents: Read & write`, `Pull requests: Read & write` (như M2).

## Bước 2 — Biến môi trường (`/etc/luna/luna.env`)

```
PUBLIC_BASE_URL=https://luna.fechtin.com
GITHUB_OAUTH_CLIENT_ID=Iv1.xxxxxxxx
GITHUB_OAUTH_CLIENT_SECRET=xxxxxxxx
GITHUB_APP_SLUG=luna-maintenance-bot
WEB_SESSION_SECRET=$(openssl rand -hex 32)
BOT_TOKEN_ENC_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
DEDICATED_CONTAINER_ENABLED=false
```

Thiếu 4 biến đầu ⇒ trang `/` báo "chưa cấu hình" (wizard tắt an toàn). `BOT_TOKEN_ENC_KEY`
**đổi là mất** mọi token bot riêng đã lưu → giữ ổn định.

## Bước 3 — Phơi webhook qua Caddy (đã có cho Google Chat)

`PUBLIC_BASE_URL` phải HTTPS công khai. Tái dùng `luna.fechtin.com` (reverse_proxy → `127.0.0.1:8000`).
Webhook bot riêng: Telegram sẽ POST `https://luna.fechtin.com/webhook/telegram/<bot_id>` kèm header
`X-Telegram-Bot-Api-Secret-Token` = `bot.webhook_secret` (sinh tự động khi provision).

> **Bot Luna chung** vẫn chạy `TELEGRAM_MODE=polling` như cũ. **Bot riêng** chạy webhook — hai cơ
> chế song song, không xung đột (mỗi bot riêng có token + webhook riêng).

## Bước 4 — Người dùng cuối (luồng "bot riêng")

1. Mở `https://luna.fechtin.com` → **Đăng nhập GitHub** → **Cấp quyền repo** (chọn repo).
2. Chọn *Bot riêng* → mở Telegram `@BotFather` → `/newbot` → đặt tên → **dán token** vào wizard.
3. Bấm **Tạo bot** → wizard validate token (`getMe`), set webhook, hiện **nút mở bot + `/start <token>`**.
4. Bấm nút → nhắn bot → gửi yêu cầu bảo trì. Người tạo là **manager**, tự duyệt merge `main`.

Luồng "bot chung" giống hệt nhưng bỏ bước 2 (không cần token) — nhắn thẳng `@<bot chung>`.

## Tier 2 — Container riêng (tuỳ chọn, mặc định TẮT)

Bật `DEDICATED_CONTAINER_ENABLED=true` + mount Docker socket vào container luna gốc:

```yaml
# deploy/docker-compose.yml (service luna) — CHỈ khi cần container/tenant
volumes:
  - /var/run/docker.sock:/var/run/docker.sock
```

⚠️ **Rủi ro bảo mật**: socket Docker ≈ quyền root trên host. Chỉ bật có chủ đích cho tenant trả phí.
`provision_container()` chạy `docker run` một bản luna đơn-bot cho tenant (polling, token + `DATABASE_URL`
riêng `luna_tenant_<id>` — ops phải tạo DB này trước), tên `luna-tenant-<id>`. Vì đơn-bot nên không
cần route đa bot bên trong → tái dùng nguyên code path cũ.

## Kiểm thử

- Unit/integration: `pytest -q` (xanh — gồm `test_provisioning`, `test_multibot`, `test_github_oauth`,
  `test_web`).
- E2E: làm theo Bước 4 với 1 repo sandbox + 1 bot test → nhắn → chạy hết FSM tới PR `dev` → tự duyệt `main`.
