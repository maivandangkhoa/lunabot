# Kế hoạch: luna — Giao diện quản lý (Admin Console) đa tenant

> Mục tiêu: web console để **quản lý tenant** và **các dự án (repositories) trong mỗi tenant**,
> thiết kế để **scale khi triển khai cho nhiều công ty**.
>
> Chốt với user:
> - **API-first**: backend JSON tách khỏi presentation (router `/api/v1/*`). Đổi UI sau không đụng backend.
> - **RBAC + tenant-scoping**: `operator` (chủ SaaS) thấy mọi tenant; `tenant_admin` chỉ thấy tenant mình.
> - **UI**: HTMX + Jinja2 server-render trong chính FastAPI (chung container, không node build). Reversible → SPA sau.

## Nguyên tắc thiết kế (scale-ready)
1. **Tách lớp rõ**: `api/` (JSON, không biết HTML) ⇄ `web/` (render HTML, gọi service chung) ⇄ `services/` (logic dùng chung cho cả chat & web).
2. **Tenant isolation ở tầng query**: mọi truy vấn đi qua dependency `scoped(...)` — operator bỏ filter, tenant_admin ép `tenant_id`. Không tin client gửi tenant_id.
3. **DRY với chat**: tái dùng `onboarding.py` (create_tenant/add_repository/create_user/regenerate_link_token). Nếu cần, rút logic chung ra `app/services/` để cả `admin_commands.py` (chat) và web cùng dùng.
4. **≤500 LOC/file**: tách router theo resource; tách service theo domain.
5. **Bảo mật**: password hash (bcrypt), session cookie ký (itsdangerous/SessionMiddleware), CSRF cho form, không log secret/token.

## Quan hệ với model hiện có
- `User` hiện tại = tài khoản **chat** (platform_user_id, link_token), KHÔNG có mật khẩu → giữ nguyên cho workflow bot.
- Thêm bảng **mới** `admin_users` cho đăng nhập **web** (tách biệt, sạch):
  - `id, tenant_id (nullable → NULL = operator scope-all), email (unique), password_hash, role (operator|tenant_admin), is_active, created_at, last_login_at`.
- Lý do tách bảng thay vì nhồi cột vào `User`: định danh web (email/password) khác định danh chat (platform_user_id); tránh churn workflow bot; rạch ròi quyền operator vs vai trò chat.

---

## Per-tenant channels (Mức 2 — mỗi tenant có bot/app RIÊNG) ⚠️ phần nặng nhất
> User chốt: mỗi công ty dùng bot Telegram / Google Chat app **riêng** (token riêng, brand riêng),
> KHÔNG dùng chung @LunaMaiBot. Đây là thay đổi backend lớn, không chỉ UI.

### Hiện trạng phải đổi
- Credential đang **global** trong `config.py` (`telegram_bot_token`, `google_chat_sa_json`) → chuyển sang **per-tenant lưu trong DB (mã hoá)**.
- Routing đang theo `User.platform`; tenant suy từ user. Với nhiều bot phải biết **tin đến từ bot nào → tenant nào** TRƯỚC khi tìm user.
- Prod đang **polling 1 bot**. Nhiều bot ⇒ **bắt buộc webhook mode** (1 endpoint route N bot theo path/secret). N poller không scale. → cần expose webhook cho Telegram giống Google Chat đã làm (`luna.example.com` qua caddy).

### Schema mới: `channel_configs`
`id, tenant_id, platform (telegram|google_chat), enabled, credential_encrypted (Fernet),
inbound_secret (random/channel — để route webhook), label/bot_username, meta_json
(vd project_number cho GChat), created_at, last_verified_at`.
- **Mã hoá at-rest** bằng Fernet (`cryptography` đã có sẵn qua PyJWT[crypto]); key từ env `CHANNEL_ENC_KEY`. **KHÔNG bao giờ log**, UI chỉ hiện 4 ký tự cuối.

### Inbound routing (đa bot)
- **Telegram**: webhook `POST /webhook/telegram/{inbound_secret}` (hoặc match header `X-Telegram-Bot-Api-Secret-Token` → channel). Tra `channel_configs` → tenant → dựng adapter bằng token của tenant đó.
- **Google Chat**: route theo `aud`(project_number)/path → `channel_configs` → tenant. Mỗi tenant 1 SA.
- **Outbound**: adapter dựng từ credential của channel (giải mã lúc dùng, không log).

### Định danh user phải scope lại
- `uq_platform_user (platform, platform_user_id)` sẽ **đụng** nếu cùng người ở 2 tenant (Telegram user id là global). → đổi sang **`(channel_id, platform_user_id)`** hoặc `(tenant_id, platform, platform_user_id)`. Migration + cập nhật `get_user_by_platform`/dispatcher.

### Tác động code
- `dispatcher.py`: thêm bước resolve channel → tenant TRƯỚC; dựng adapter từ channel_config (hiện adapter dựng từ global settings ở `main.py`).
- `channels/*`: adapter nhận credential qua constructor (đã sẵn) — chỉ đổi nguồn cấp credential.
- `poller.py`: với Mức 2 chủ yếu dùng webhook; giữ polling như fallback dev 1-bot.
- `main.py`: route webhook động theo `inbound_secret`.

### Admin UI (tab Channels trong Tenant detail)
- Thêm channel: chọn platform, dán token/SA JSON → lưu mã hoá; hiện **URL webhook** để khách cấu hình bên Telegram/Google.
- Enable/disable, **Test connection** (Telegram `getMe`, GChat spaces ping), hiện trạng `last_verified_at`, mask credential.

---

## Phases (W = Web/Admin console). Dừng cho user review sau mỗi phase.

### W0 — Nền tảng & deps
- `requirements.txt`: thêm `jinja2`, `python-multipart` (form), `passlib[bcrypt]` (hash), `itsdangerous` (SessionMiddleware đã có sẵn trong starlette).
- `config.py`: thêm `admin_enabled: bool`, `admin_session_secret: str`, `admin_bootstrap_email/password` (tạo operator đầu tiên nếu DB rỗng).
- Model `AdminUser` + **Alembic migration** mới.
- Bootstrap: startup tạo operator từ env nếu chưa có admin_user nào (idempotent).
- Tests: model + bootstrap.

### W1 — API layer + Auth/RBAC (lõi scale)
- `app/api/schemas.py` — Pydantic in/out (TenantOut, RepoIn/Out, …).
- `app/api/deps.py` — `current_account` (đọc session), `require_operator`, `scoped_tenant_query`, `assert_can_access(tenant_id)`.
- `app/api/auth.py` — `POST /api/v1/auth/login` (verify hash → set session), `/logout`, `/me`.
- `app/api/tenants.py` — list/create/get/update/delete tenant (create/delete: operator-only; list: scoped).
- `app/api/repositories.py` — list/create/update/delete repo trong 1 tenant (validate repo_full_name `owner/name`, gh_installation_id, base/prod branch; tôn trọng `uq_repo_per_tenant`).
- `main.py`: thêm `SessionMiddleware`; include routers dưới `/api/v1`.
- Tests: CRUD + **RBAC** (tenant_admin KHÔNG đọc/sửa được tenant khác → 403/404), auth login/logout.

### W2 — Admin UI: Tenant + Repo (HTMX + Jinja2) ← phần cốt lõi user yêu cầu
- `app/web/__init__.py` router (mount `/admin`), `templates/`, `static/` (1 file CSS nhỏ, không build).
- `templates/base.html` — layout, nav, flash, include HTMX (CDN hoặc static).
- Trang **Login** (`/admin/login`).
- Trang **Tenants** (`/admin`): bảng tenant (operator thấy tất cả; tenant_admin redirect thẳng tenant mình). Nút tạo tenant (operator).
- Trang **Tenant detail** (`/admin/tenants/{id}`): thông tin tenant + **bảng Repositories** với add/edit/remove (HTMX swap, không reload full page).
- Web gọi qua **service layer** (không gọi HTTP nội bộ) để đơn giản; cùng logic với API.
- Tests: smoke render + form post (TestClient), auth guard redirect.

### WC — Per-tenant channels (Mức 2) ⚠️ phase nặng nhất, tách riêng
> Làm SAU console lõi (W2) vì cần UI để quản channel, và đây là thay đổi backend lớn.
- Model `channel_configs` + migration; helper mã hoá Fernet (`app/crypto.py`), env `CHANNEL_ENC_KEY`.
- `app/channels/resolver.py`: inbound_secret/aud → channel_config → tenant + dựng adapter (giải mã credential).
- `main.py`: `POST /webhook/telegram/{inbound_secret}` (route động); GChat route theo aud/path.
- `dispatcher.py`: resolve channel→tenant trước; bỏ phụ thuộc credential global.
- Migration đổi unique định danh user → `(channel_id, platform_user_id)`; cập nhật `get_user_by_platform`.
- API `app/api/channels.py` + tab **Channels** (thêm/test/enable/mask credential, hiện URL webhook).
- Deploy: expose webhook Telegram qua caddy (như GChat); giữ polling làm fallback dev.
- Tests: routing đa bot, mã hoá at-rest (không lộ token), RBAC, định danh user scoped.

### W3 — Quản lý Users trên UI (tab trong tenant detail)
- Tái dùng `onboarding.create_user` / `regenerate_link_token` / `admin_commands` logic.
- Tab **Users**: list (role, đã-link / link_token), invite (role + tên → hiện `/start <token>`), đổi role, unlink (cấp token mới).
- API tương ứng `app/api/users.py` (scoped theo tenant).
- Tests.

### W4 — Requests dashboard (read-only, giám sát)
- `app/api/requests.py` (read-only) + tab **Requests** trong tenant detail.
- List request theo tenant/repo: status FSM, PR link, updated_at; filter theo status.
- Request detail: timeline `request_events` (kind/direction/payload), approvals.
- Mục tiêu: operator/tenant_admin giám sát bot đang chạy gì cho từng công ty.
- Tests.

### W5 — Hardening & deploy
- CSRF token cho mọi form POST; rate-limit /login (đơn giản, in-memory hoặc DB).
- Audit: log thao tác quản trị (tạo/xoá tenant, đổi role) — có thể tái dùng `request_events` hoặc bảng riêng nhỏ.
- `deploy/`: phục vụ `static/`, cập nhật `env.example` (ADMIN_*), docker-compose; doc `deploy/admin-console.md`.
- Cập nhật memory (`MEMORY.md` + architecture-decisions) + `tasks/lessons.md`.

---

## Cây thư mục dự kiến (sau W2)
```
app/
  api/
    __init__.py        # APIRouter gốc /api/v1
    deps.py            # auth + RBAC + tenant scoping
    schemas.py
    auth.py
    tenants.py
    repositories.py
    users.py           # W3
    requests.py        # W4 (read-only)
    channels.py        # WC
  crypto.py            # WC — Fernet encrypt/decrypt credential
  channels/resolver.py # WC — inbound → channel_config → tenant + adapter
  services/            # logic dùng chung chat + web (rút dần khi cần)
  web/
    __init__.py        # router /admin (Jinja2 + HTMX)
  templates/
    base.html  login.html  tenants.html  tenant_detail.html
  static/
    app.css
alembic/versions/xxxx_admin_users.py
tests/test_api_tenants.py  test_api_rbac.py  test_web_admin.py
```

## Rủi ro / lưu ý
- **Migration chạm DB prod** (Cloud VM): test migration trên SQLite + Postgres staging trước.
- **Operator credential**: bootstrap qua env, đổi mật khẩu sau lần đầu (W5).
- **Không trùng chat admin**: web quản tenant/repo (chat chưa có); user-management trùng `admin_commands` → giữ 1 nguồn logic (`onboarding`/`services`).
- Bắt đầu **W0→W2** trước (đáp ứng đúng yêu cầu "quản lý tenant + dự án trong tenant"); W3–W5 mở rộng.
```
