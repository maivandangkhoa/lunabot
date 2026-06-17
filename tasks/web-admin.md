# Kế hoạch C — Web Admin cho luna

> Bổ sung **giao diện quản trị web** cạnh luồng vận hành chat-only. Mục tiêu: quản lý
> tenant/repo/user/role và **xem request + audit** mà không cần SSH/SQL.

## Mục tiêu & phạm vi
- **Super-admin (Acme-corp)**: quản tất cả tenant/repo/user, xem mọi request.
- **Tenant-admin**: chỉ quản tenant của mình (user/role/repo) + xem request tenant đó.
- **Read + Write**: CRUD tenant/repo/user; request thì **read-only** + vài hành động (huỷ).

KHÔNG làm (giai đoạn này): self-serve onboarding công khai, billing, SSO doanh nghiệp.

## Kiến trúc đề xuất
- **Server-rendered**: FastAPI + **Jinja2 + HTMX + Tailwind (CDN)**. 1 container, không cần
  build Node, hợp phong cách repo (đơn giản, ít phụ thuộc). (SPA React để dành nếu cần.)
- Package mới `app/web/`:
  ```
  app/web/
    __init__.py
    deps.py          # session/auth dependency, RBAC
    auth.py          # login/logout, hash mật khẩu
    routes_dashboard.py
    routes_tenants.py
    routes_repos.py
    routes_users.py
    routes_requests.py
    templates/       # base.html + từng trang (Jinja2)
  ```
  Mount dưới `/admin`. Tách router theo resource để giữ ≤500 LOC/file.
- **Tái dùng**: `app/onboarding.py` (create_user/tenant/repo, regenerate_token), `app/models.py`.
- **Auth (đa tenant ngay từ đầu — ĐÃ CHỐT)**: session cookie ký bằng `SECRET_KEY`. Mật khẩu
  hash (passlib/bcrypt). Bảng `admin_accounts` (email, password_hash, **scope: super|tenant**,
  tenant_id nullable) qua migration `0002_admin_accounts`. RBAC: `super` thấy mọi tenant;
  `tenant` chỉ thấy/sửa tenant của mình (mọi query lọc theo tenant_id, chặn cross-tenant).
- **Bảo mật**: CSRF token cho form POST; cookie HttpOnly+SameSite+Secure; audit hành động admin;
  rate-limit login.

## Trang (MVP)
1. **/admin/login** — đăng nhập.
2. **/admin** — dashboard: đếm tenant/repo/user/request theo status.
3. **/admin/tenants** — list/create/detail.
4. **/admin/tenants/{id}/repos** — list/add/edit repo (repo_full_name, installation_id, branches).
5. **/admin/tenants/{id}/users** — list/create (hiện link_token)/set-role/unlink.
6. **/admin/requests** — list + filter status; **detail**: timeline `request_events`,
   `approvals`, link PR; nút **Huỷ** (CANCELLED).

## Phơi ra ngoài (HTTPS) — ĐÃ CHỐT: subdomain qua edge-caddy
- Bạn thêm **DNS** `luna.example.com` (Cloudflare, proxied) → `REDACTED-IP`.
- Tôi: **nối container `luna` vào network của edge-caddy** (để Caddy gọi `luna:8000` qua tên
  container — vì luna đang bind `127.0.0.1`, Caddy không với tới qua host). Thêm 1 site-block
  vào `~/edge-proxy/Caddyfile` (có backup, `caddy reload` mềm), dùng origin cert `*.example.com` sẵn có.
- KHÔNG đụng cấu hình edge-proxy/internal hiện tại. Chỉ public sau khi đã có CSRF + secure cookie.

## Mốc xây dựng (mỗi mốc chạy được, dừng review)
- **W0 — Scaffold + Auth(RBAC) + Dashboard**: package `app/web/`, base layout (Jinja2+HTMX+Tailwind),
  migration `0002_admin_accounts`, login/logout đa tenant (super|tenant scope), CSRF + secure cookie,
  dashboard đếm theo scope. CLI `scripts/admin_account.py` tạo tài khoản super-admin. Test qua SSH tunnel.
- **W1 — Phơi ra ngoài**: nối luna vào network caddy + site-block `luna.example.com` (bạn thêm DNS),
  rate-limit login. → truy cập trình duyệt thật.
- **W2 — Tenants + Repos CRUD** (super: mọi tenant; tenant-admin: tenant mình).
- **W3 — Users management** (list/create→hiện link_token/role/unlink) — tái dùng onboarding.
- **W4 — Requests list + detail** (timeline `request_events` + approvals + PR, nút Huỷ).
- **W5 — Audit log hành động admin + polish** (search/filter, pagination).

## Test
- TestClient: auth (yêu cầu login, sai mật khẩu, **RBAC chặn cross-tenant**), CSRF, CRUD
  tenant/repo/user, render request detail. Tái dùng fixture SQLite + fakes.

## Đã chốt (2026-06-16)
1. Stack: **Jinja2 + HTMX + Tailwind CDN** (server-rendered, 1 container).
2. Auth: **đa tenant + RBAC ngay từ đầu** (super | tenant scope).
3. Phơi ra: **subdomain `luna.example.com` qua edge-caddy** (bạn thêm DNS, tôi nối network + Caddy block).
